import { execFile, spawn, type ChildProcess } from 'node:child_process'
import { cp, mkdtemp, open, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { promisify } from 'node:util'

import { test as base, expect, type Page } from '@playwright/test'

const run = promisify(execFile)

// Playwright sets `FORCE_COLOR`, which would color the JSON the fixture reads and the engine log.
const { FORCE_COLOR: _, ...environment } = process.env

const consoleDirectory = path.resolve(import.meta.dirname, '..')
const projectSource = path.join(import.meta.dirname, 'project')
const ceres = process.env.CERES_BINARY ?? path.resolve(consoleDirectory, '../.venv/bin/ceres')

/** Each worker's engine listens on its own port, so workers never share an engine. */
const basePort = 18500

export const password = 'abcdefgh'

/** A workspace on `@device` holding a "Procedures" widget open on `hold`, tall enough to show its
buttons. */
const proceduresWorkspace = {
  layout: [
    {
      height: 500,
      widgets: [
        {
          type: 'procedures',
          name: 'Procedures',
          procedureAddress: '@device',
          procedureType: 'action',
          procedureName: 'hold',
        },
      ],
    },
  ],
  meta: {},
}

/** A log entry as `ceres logs select` prints it. */
export type EngineLog = {
  address: string
  content: string
  level: string
}

/** An engine running the fixture project from a scratch copy, with an admin and a viewer who
may view `@device` but not operate it. */
export class Engine {
  readonly url: string

  constructor(
    readonly directory: string,
    readonly port: number,
    readonly process: ChildProcess,
    readonly logPath: string,
  ) {
    this.url = `http://localhost:${port}`
  }

  /** Runs a `ceres` command in the project and returns its standard output. */
  async ceres(...args: string[]): Promise<string> {
    const { stdout } = await run(ceres, args, { cwd: this.directory, env: environment })
    return stdout
  }

  /** Logs `address` stored whose content contains `text`. */
  async logs(address: string, text: string): Promise<EngineLog[]> {
    const output = await this.ceres(
      'logs',
      'select',
      '--address',
      address,
      '--contains',
      text,
      '--format',
      'json',
    )
    return output
      .split('\n')
      .filter((line) => line !== '')
      .map((line) => JSON.parse(line) as EngineLog)
  }

  static async start(port: number): Promise<Engine> {
    const directory = await mkdtemp(path.join(tmpdir(), 'ceres-e2e-'))
    await cp(projectSource, directory, { recursive: true })
    await writeFile(path.join(directory, 'ceres.yaml'), configuration(port))

    const setup = async (...args: string[]) => {
      await run(ceres, args, { cwd: directory, env: environment })
    }

    const user = async (name: string, ...flags: string[]): Promise<string> => {
      const { stdout } = await run(
        ceres,
        [
          'users',
          'create',
          '--username',
          name,
          '--email',
          `${name}@example.com`,
          '--password',
          password,
          '--field',
          'id',
          '--format',
          'csv',
          '--no-header',
          ...flags,
        ],
        { cwd: directory, env: environment },
      )
      return stdout.trim()
    }

    await setup('database', 'migrate', '--yes')
    await user('admin', '--admin')
    const viewer = await user('viewer')
    await setup(
      'user-permissions',
      'create',
      '--user-id',
      viewer,
      '--target-type',
      'component',
      '--target',
      '@device',
      '--level',
      'view',
    )
    await setup(
      'workspaces',
      'create',
      '--name',
      'Procedures',
      '--scope',
      '@device',
      '--data',
      JSON.stringify(proceduresWorkspace),
    )

    const logPath = path.join(directory, 'engine.log')
    const log = await open(logPath, 'w')
    const child = spawn(ceres, ['run'], {
      cwd: directory,
      env: environment,
      stdio: ['ignore', log.fd, log.fd],
    })
    await log.close()

    const engine = new Engine(directory, port, child, logPath)
    await engine.ready()
    return engine
  }

  /** Waits until the engine serves the console. */
  async ready(): Promise<void> {
    await expect
      .poll(
        async () => {
          if (this.process.exitCode != null) {
            throw new Error(`The engine exited with ${this.process.exitCode}, see ${this.logPath}`)
          }

          try {
            return (await fetch(this.url)).status
          } catch {
            return null
          }
        },
        { timeout: 60_000 },
      )
      .toBe(200)
  }

  async stop(): Promise<void> {
    if (this.process.exitCode == null) {
      const exited = new Promise((resolve) => this.process.once('exit', resolve))
      this.process.kill('SIGTERM')
      await exited
    }
  }

  async remove(): Promise<void> {
    await rm(this.directory, { recursive: true, force: true })
  }
}

function configuration(port: number): string {
  return `database:
  type: sqlite
  path: ./database.sqlite
server:
  http:
    port: ${port}
  authentication:
    secret: an-adequately-long-end-to-end-signing-secret
console:
  title: End To End
components:
  - name: device
    class: device.Device
`
}

/** Signs `username` in through the login page. */
export async function login(page: Page, username: string): Promise<void> {
  await page.goto('/login')
  await page.getByPlaceholder('Username').fill(username)
  await page.getByPlaceholder('Password').fill(password)
  await page.getByRole('button', { name: 'Submit' }).click()
  await page.waitForURL('/')
}

export const test = base.extend<{ engineLog: undefined }, { engine: Engine }>({
  engine: [
    // Playwright reads a fixture's dependencies from its first parameter's destructuring.
    // eslint-disable-next-line no-empty-pattern
    async ({}, use, workerInfo) => {
      const engine = await Engine.start(basePort + workerInfo.parallelIndex)
      await use(engine)
      await engine.stop()
      await engine.remove()
    },
    { scope: 'worker' },
  ],
  engineLog: [
    async ({ engine }, use, testInfo) => {
      await use(undefined)
      if (testInfo.status !== testInfo.expectedStatus) {
        await testInfo.attach('engine.log', { path: engine.logPath, contentType: 'text/plain' })
      }
    },
    { auto: true },
  ],
  baseURL: async ({ engine }, use) => {
    await use(engine.url)
  },
})

export { expect }
