import { reactive } from 'vue'

const mock = reactive({
  config: {
    units: {
      ['ctd-101' as string]: {
        label: 'CTD101',
        connections: {
          ['science' as string]: {
            module: 'ceres.standard.connections.tcp',
            configuration: {
              ip: '10.20.15.20',
              port: 4000,
            },
            enabled: true,
            state: 'connected',
            target: '10.20.15.20:4000',
          },
          ['control' as string]: {
            module: 'ceres.standard.connections.tcp',
            configuration: {
              ip: '10.20.15.20',
              port: 4001,
            },
            enabled: true,
            state: 'connected',
            target: '10.20.15.20:4001',
          },
        },
        drivers: {
          ['main' as string]: {
            module: 'project.instruments.ctd.drivers.main',
            connections: {
              science: 'science',
              control: 'control',
            },
            elements: [
              {
                type: 'gauge',
              },
            ],
          },
        },
        pipelines: {
          ['conductivity' as string]: {
            module: 'project.instruments.ctd.pipelines.conductivity',
          },
        },
      },
      ['ctd-102' as string]: {
        label: 'CTD102',
        connections: {
          ['science' as string]: {
            module: 'ceres.standard.connections.tcp',
            configuration: {
              ip: '10.20.30.20',
              port: 4000,
            },
            enabled: false,
            state: 'disabled',
            target: '10.20.30.20:4000',
          },
          ['control' as string]: {
            module: 'ceres.standard.connections.tcp',
            configuration: {
              ip: '10.20.30.20',
              port: 4001,
            },
            enabled: true,
            state: 'disconnected',
            target: '10.20.30.20:4001',
          },
        },
        drivers: {
          ['main' as string]: {
            module: 'project.instruments.ctd.drivers.main',
            connections: {
              science: 'science',
              control: 'control',
            },
            elements: [],
          },
        },
        pipelines: {
          ['conductivity' as string]: {
            module: 'project.instruments.ctd.pipelines.conductivity',
          },
        },
      },
      ['tmp-101' as string]: {
        label: 'TMP101',
        connections: {},
        drivers: {},
        pipelines: {},
      },
    },
  },
})

export default mock

export type Unit = typeof mock.config.units[string]
export type Connection = Unit['connections'][string]
export type Driver = Unit['drivers'][string]
export type Pipelines = Unit['pipelines'][string]
export type ElementInfo = Driver['elements']
