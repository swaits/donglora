# DongLoRa Examples

Example scripts demonstrating the [Python client library](../clients/python/).

## Running

```sh
just rx                     # receive packets
just tx                     # transmit a packet
just ping-pong --role tx    # two-dongle ping-pong demo
just test-commands          # exercise all DongLoRa commands
just bridge --mode server   # LoRa bridge over TCP
just meshcore               # MeshCore packet decoder
just orac                   # MeshCore AI bot (needs ANTHROPIC_API_KEY)
just telemetry              # MeshCore repeater telemetry monitor
```

## Depends On

- [clients/python](../clients/python/) — the `donglora` client library
