# MeshCore Example

This is a **protocol implementation** built on top of DongLoRa. The DongLoRa
firmware itself is protocol-agnostic — it just gives you a LoRa radio pipe.
MeshCore is one of many possible protocols you can run over it.

## What's here

- **meshcore_rx.py** — MeshCore packet decoder, Watchman mesh health reporter
- **channels.csv** — 276 known MeshCore channels (Public + hashtag channels)
- **corpus/** — Test vectors for MeshCore packet decoders

## Usage

From the `examples/` directory:

```sh
just meshcore [PORT]
```

Connects to a DongLoRa device, configures the radio for the MeshCore
frequency/modulation, and decodes received packets in real time.

## Running the test corpus

From the `examples/` directory:

```sh
uv run --extra meshcore meshcore/corpus/validate.py
```
