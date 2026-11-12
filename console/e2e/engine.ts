import { execFile, spawn, type ChildProcess } from 'node:child_process'
import { cp, mkdtemp, open, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { promisify } from 'node:util'

import { expect } from '@playwright/test'

const run = promisify(execFile)

// Playwright sets `FORCE_COLOR`, which would color the JSON the engine reads back and its log.
const { FORCE_COLOR: _, ...environment } = process.env

const consoleDirectory = path.resolve(import.meta.dirname, '..')
const projectSource = path.join(import.meta.dirname, 'project')
const ceres = process.env.CERES_BINARY ?? path.resolve(consoleDirectory, '../.venv/bin/ceres')

/** The password of every account the tests create. */
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

export type EngineUser = {
  id: string
  username: string
}

/** A stored user as `ceres users select` prints it. */
export type EngineUserRecord = EngineUser & {
  email: string
  admin: boolean
  disabled: boolean
}

export type EngineGroup = {
  id: string
  name: string
  description: string | null
}

export type EngineLog = {
  address: string
  content: string
  level: string
}

export type AccessLevel = 'view' | 'operate' | 'manage'

/** An engine running the fixture project from a scratch directory, administered through the
`ceres` command. */
export class Engine {
  readonly url: string
  readonly logPath: string

  // Tests share an engine, so every account and group they create takes a fresh name.
  private created = 0

  private constructor(
    readonly directory: string,
    readonly port: number,
    private readonly process: ChildProcess,
  ) {
    this.url = `http://localhost:${port}`
    this.logPath = path.join(directory, 'engine.log')
  }

  /** Copies the fixture project into a scratch directory, sets up its database and the
  "Procedures" workspace, and runs it on `port`. */
  static async start(port: number): Promise<Engine> {
    const directory = await mkdtemp(path.join(tmpdir(), 'ceres-e2e-'))
    await cp(projectSource, directory, { recursive: true })
    await writeFile(path.join(directory, 'ceres.yaml'), configuration(port))
    await command(directory, 'database', 'migrate', '--yes')
    await command(
      directory,
      'workspaces',
      'create',
      '--name',
      'Procedures',
      '--scope',
      '@device',
      '--data',
      JSON.stringify(proceduresWorkspace),
    )

    const log = await open(path.join(directory, 'engine.log'), 'w')
    const child = spawn(ceres, ['run'], {
      cwd: directory,
      env: environment,
      stdio: ['ignore', log.fd, log.fd],
    })
    await log.close()

    const engine = new Engine(directory, port, child)
    await engine.ready()
    return engine
  }

  /** Runs a `ceres` command in the project and returns its standard output. */
  ceres(...args: string[]): Promise<string> {
    return command(this.directory, ...args)
  }

  /** `name` with a fixed-width counter, so no name contains another and a search finds one. */
  private fresh(name: string): string {
    return `${name}-${String(++this.created).padStart(3, '0')}`
  }

  /** Creates an account named after `name` with the shared password, an administrator when
  `admin` is set. */
  async createUser(name: string, { admin = false } = {}): Promise<EngineUser> {
    const username = this.fresh(name)
    const output = await this.ceres(
      'users',
      'create',
      '--username',
      username,
      '--email',
      `${username}@example.com`,
      '--password',
      password,
      ...(admin ? ['--admin'] : []),
      '--format',
      'json',
    )
    return JSON.parse(output) as EngineUser
  }

  /** The stored user named `username`, or `null` when there is none. */
  async user(username: string): Promise<EngineUserRecord | null> {
    return first(await this.ceres('users', 'select', '--username', username, '--format', 'json'))
  }

  /** Creates a group named after `name`. */
  async createGroup(name: string): Promise<EngineGroup> {
    const output = await this.ceres(
      'groups',
      'create',
      '--name',
      this.fresh(name),
      '--format',
      'json',
    )
    return JSON.parse(output) as EngineGroup
  }

  /** The stored group named `name`, or `null` when there is none. */
  async group(name: string): Promise<EngineGroup | null> {
    return first(await this.ceres('groups', 'select', '--name', name, '--format', 'json'))
  }

  /** Whether `user` is a member of `group`. */
  async isMember(user: EngineUser, group: EngineGroup): Promise<boolean> {
    const output = await this.ceres(
      'group-memberships',
      'count',
      '--user-id',
      user.id,
      '--group-id',
      group.id,
    )
    return Number(output.trim()) > 0
  }

  async addMember(user: EngineUser, group: EngineGroup): Promise<void> {
    await this.ceres('group-memberships', 'create', '--user-id', user.id, '--group-id', group.id)
  }

  /** Grants `user` `level` access to the component at `address`. */
  async grant(user: EngineUser, address: string, level: AccessLevel): Promise<void> {
    await this.ceres(
      'user-permissions',
      'create',
      '--user-id',
      user.id,
      '--target-type',
      'component',
      '--target',
      address,
      '--level',
      level,
    )
  }

  /** The stored logs of `address` whose content contains `text`. */
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
    return lines(output).map((line) => JSON.parse(line) as EngineLog)
  }

  async stop(): Promise<void> {
    if (this.process.exitCode == null) {
      const exited = new Promise((resolve) => this.process.once('exit', resolve))
      this.process.kill('SIGTERM')
      await exited
    }

    await rm(this.directory, { recursive: true, force: true })
  }

  /** Waits until the engine serves the console. */
  private async ready(): Promise<void> {
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
}

async function command(directory: string, ...args: string[]): Promise<string> {
  const { stdout } = await run(ceres, args, { cwd: directory, env: environment })
  return stdout
}

function lines(text: string): string[] {
  return text.split('\n').filter((line) => line !== '')
}

/** The first record of JSON lines output, or `null` when there is none. */
function first<T>(output: string): T | null {
  const [line] = lines(output)
  return line == null ? null : (JSON.parse(line) as T)
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
    allow-impersonate: true
console:
  title: End To End
components:
  - name: device
    class: device.Device
`
}
