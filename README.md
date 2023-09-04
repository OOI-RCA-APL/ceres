# Ceres

![CI](https://github.com/OOI-RCA-APL/ceres/actions/workflows/ci.yaml/badge.svg)

Ceres is a Python framework for data collection, monitoring and device control.

| ⚠                                                                                                                                  |
| ---------------------------------------------------------------------------------------------------------------------------------- |
| _This project is in active development and will likely change drastically. No backwards compatibility is guaranteed at this time._ |

## Why Ceres?

Collecting data and storing somewhere is conceptually a simple task, but it quicky becomes complex as requirements change and grow, the number of data sources/projects increases, and/or command and control of external devices is required.

This increasing complexity is difficult to manage, and tends towards brittle, unreliable systems that are difficult to maintain.

Ceres aims to solve this problem.

### Features

1. **Reliability**

   Ceres will stay alive in the face of external failures. The network or an external device could fail, the database could be unreachable, your code may have bugs that eventually cause a crash. Ceres allows these issues to be contained and handled gracefully.

2. **Error Reporting**

   When something _does_ go wrong, issues can be automatically reported to team members. Your team will know what happened and be provided with information to address the problem.

3. **Scalability**

   Ceres allows collecting data an arbitrary number of sources simultaneously. Some may be sending data at a high rate, others may be sending data it infrequently. Ceres will handle the load.

4. **Flexibility**

   You may be collecting data from many different sources, spanning across any number of separate projects, which all have distinct data formats, protocols and quirks that make them maddenly unique.

   Writing and maintaining masses of one-off code for each data source or project is not ideal. Ceres is flexible enough to accommodate these differences, but take the burden of handling common requirements off your back.

5. **Zero Boilerplate UI**

   The Ceres web console will show you what the system is doing now, and what has happened in the past. The web console helps answer questions like:

   - Are we still connected to a given device or network?
   - When did a given connection drop? Why?
   - What messages have we sent/received in the past week? The past year?
   - What messages are we sending/receiving right now?
   - What does the collected data look like? Is it valid?
   - What errors are currently being reported?
   - How has the data changed over time? Are there obvious trends?
   - How much data do we have? How much are we collecting per day?
   - Why did a given job fail? How often is it running?

   The web console will also allow you to control your components without touching a CLI. You can stop/start components, enable/disable components, send messages, call arbitrary procedures, and more.

   Setting up a user interface to answer these questions for every project is a truly _massive_ amount of work that Ceres will handle _for you_.

6. **Testing**

   Ceres components of are completely testable in isolation. They can be created and run in-code without any configuration files. Additionally do not have to set up and tear down external database just to run tests. If a database is not assigned to a component, it will create a temporary one automatically.

7. **Deployment**

   Ceres cross platform and easy to deploy. It can run on your laptop, on a server, or on a Raspberry Pi with minimal effort.

8. **Configuration**

   Ceres' configuration is centralized, understandable, easy to update, reload, parse and is automatically checked for correctness. Configuration can be updated without restarting the entire system, only components with changed configurations will be recreated.

## Documentation

To learn more about Ceres, take a look at our documentation.

| Page                                 | Description                                           |
| ------------------------------------ | ----------------------------------------------------- |
| [Overview](./docs/overview.md)       | Learn more about Ceres and how to use it effectively. |
| [Development](./docs/development.md) | How to help improve the Ceres project itself.         |
