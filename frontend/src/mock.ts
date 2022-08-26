import { reactive } from 'vue'
import type { ElementInfo } from './element'

const mock = reactive({
  config: {
    units: {
      ['ctd-101' as string]: {
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
                name: 'Salinity',
                type: 'number',
                value: 10000,
                unit: 'ppm',
              },
              {
                name: 'Temperature',
                type: 'gauge',
                value: 25.2,
                unit: '°C',
                range: {
                  min: 0,
                  max: 100,
                },
                color: [
                  { value: 10, color: 'blue' },
                  { value: 50, color: 'green' },
                  { value: 100, color: 'red' },
                ],
              },
              {
                name: 'Depth',
                type: 'gauge',
                value: 550,
                unit: 'm',
                range: {
                  min: 0,
                  max: 2000,
                },
              },
              {
                name: 'Internal Humidity',
                type: 'number',
                value: 75,
                unit: '%',
                color: [
                  { value: 50, color: 'green' },
                  { value: 80, color: 'orange' },
                  { value: 100, color: 'red' },
                ],
              },
              {
                name: 'Leak 1',
                label: 'Leak',
                type: 'indicator',
                value: false,
                color: 'red',
              },
              {
                name: 'Leak 2',
                label: 'Leak',
                type: 'indicator',
                value: true,
                color: 'yellow',
              },
              {
                name: 'Leak 3',
                label: 'Leak',
                type: 'indicator',
                value: true,
                color: 'red',
              },
              {
                name: 'Irridium Signal',
                label: 'Iridium',
                type: 'indicator',
                value: true,
                color: 'green',
              },
              {
                name: 'Wi-Fi Signal',
                type: 'state',
                value: 'strong',
                options: [
                  { value: 'off', color: 'grey-5', icon: 'wifi_off' },
                  { value: 'weak', color: 'negative', icon: 'wifi_1_bar' },
                  { value: 'normal', color: 'blue-5', icon: 'wifi_2_bar' },
                  { value: 'strong', color: 'positive', icon: 'wifi' },
                ],
                showOptions: false,
                verticalIcons: true,
              },
            ] as ElementInfo[],
          },
        },
        pipelines: {
          ['conductivity' as string]: {
            module: 'project.instruments.ctd.pipelines.conductivity',
          },
        },
      },
      ['ctd-102' as string]: {
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
            elements: [
              {
                name: 'Salinity',
                type: 'number',
                value: 5000,
                unit: 'ppm',
              },
              {
                name: 'Battery Level',
                type: 'halfgauge',
                value: 30,
                unit: '%',
                range: {
                  min: 0,
                  max: 100,
                },
                color: [
                  { value: 25, color: 'red' },
                  { value: 50, color: 'orange' },
                  { value: 100, color: 'green' },
                ],
              },
              {
                name: 'Reactor 1 State',
                type: 'state',
                value: 'supercritical',
                options: [
                  { value: 'offline', color: 'grey-8' },
                  { value: 'subcritical', color: 'blue-5' },
                  { value: 'critical', color: 'green' },
                  { value: 'supercritical', color: 'yellow-9' },
                  { value: 'oh shit', color: 'negative' },
                ],
                showOptions: false,
              },
              {
                name: 'Temperature',
                type: 'gauge',
                value: 75,
                unit: '°C',
                range: {
                  min: 0,
                  max: 100,
                },
                color: [
                  { value: 50, color: 'green' },
                  { value: 100, color: 'red' },
                ],
              },
              {
                name: 'Depth',
                type: 'gauge',
                value: 18000,
                unit: 'm',
                range: {
                  min: 0,
                  max: 2000,
                },
              },
              {
                name: 'Internal Humidity',
                type: 'number',
                value: 45,
                unit: '%',
                color: [
                  { value: 50, color: 'green' },
                  { value: 80, color: 'orange' },
                  { value: 100, color: 'red' },
                ],
              },
            ] as ElementInfo[],
          },
        },
        pipelines: {
          ['conductivity' as string]: {
            module: 'project.instruments.ctd.pipelines.conductivity',
          },
        },
      },
      ['tmp-101' as string]: {
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
