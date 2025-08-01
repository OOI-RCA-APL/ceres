# ruff: noqa: T201
# simulator.py

import random
import socket
from time import sleep

host = "localhost"
port = 4000

if __name__ == "__main__":
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((host, port))
    server.listen(1)

    print(f"Listening: {host}:{port}")

    try:
        while True:
            client, (client_host, client_port) = server.accept()
            print(f"Accepted: {client_host}:{client_port}")

            try:
                while True:
                    temperature = round(random.uniform(15, 30), 2)
                    humidity = round(random.uniform(30, 70), 2)
                    data = f"T:{temperature} H:{humidity}\n"

                    client.send(data.encode())
                    print(f"Sent: {data!r}")
                    sleep(1)
            except ConnectionError:
                print(f"Disconnected: {client_host}:{client_port}")
            finally:
                client.close()
    except KeyboardInterrupt:
        print("Interrupted. Exiting...")
        pass
    finally:
        server.close()
