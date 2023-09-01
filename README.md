# Ceres

![CI](https://github.com/OOI-RCA-APL/ceres/actions/workflows/ci.yaml/badge.svg)

Ceres is a Python framework for data collection, monitoring and device control.

| ⚠                                                                                                                                  |
| ---------------------------------------------------------------------------------------------------------------------------------- |
| _This project is in active development and will likely change drastically. No backwards compatibility is guaranteed at this time._ |

## Why Ceres?

Collecting data and storing somewhere is conceptually a simple task, but it quicky becomes complex as requirements change and grow, the number of data sources/projects increases, and/or command and control of external devices is required.

This ever increasing complexity is difficult to manage, and often leads to brittle, unreliable systems that are difficult to maintain. Ceres aims to solve this problem head on.

If the following requirements are important to you, Ceres may be a good fit.

1. **Reliability**

   Your system needs to stay alive, even in the face of external failures. The network or an external device could fail, the database could be unreachable, your code may have bugs that eventually cause a crash. These points of failure need to be contained and handled gracefully.

2. **Scalability**

   You are collecting data from many different sources simultaneously. Some may be sending data at a high rate, others may be sending data it infrequently. Your system needs to handle this without breaking a sweat.

3. **Error Reporting**

   When something _does_ go wrong, the issue needs to be automatically reported to team members quickly and actionably. They should know what happened and be provided enough information to address the problem.

4. **Accommodate Snowflakes**

   You are collecting data from multiple sources, spanning across any number of separate projects, which all have different data formats, protocols and quirks that make them all maddenly unique.

   Writing and maintaining masses of one-off code for each data source or project is not ideal. Your system needs be flexible enough for you to accommodate these differences, but take the burden of handling common requirements off your back.

5. **Live User Interface**

   You need to see what the system is doing now, and/or historically. You may need to answer questions like:

   - Are we still connected to a given device or network?
   - When did a given connection drop? Why?
   - What messages have we sent/received in the past week? The past year?
   - What messages are we sending/receiving right now?
   - What does the collected data look like? Is it valid?
   - What errors are currently being reported?
   - How has the data changed over time? Are there obvious trends?
   - How much data do we have? How much are we collecting per day?
   - Why did a given job fail? How often is it running?

   Setting up a user interface to answer these questions for every project is a truly _massive_ amount of work that should ideally be handled _for you_.

6. **Testing**

   You need to test your system, ensuring everything is working as expected before you deploy. Individual components of your system should be testable in isolation with a good approximation of the real world setup.

7. **Deployment**

   You need the system to be cross platform and easy to deploy. You should be able to run it on your local development machine, on a server, or on a Raspberry Pi with minimal effort.

8. **Configuration**

   System configuration should be centralized, understandable, easy to update, reload, parse and check for correctness. It should be possible to update configuration without restarting the entire system. Deploying or reverting changes should be easy.

## Documentation

To learn more about Ceres, take a look at our documentation.

| Page                                 | Description                                           |
| ------------------------------------ | ----------------------------------------------------- |
| [Overview](./docs/overview.md)       | Learn more about Ceres and how to use it effectively. |
| [Development](./docs/development.md) | How to help improve the Ceres project itself.         |
