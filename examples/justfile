set shell := ["bash", "-c"]

# Receive LoRa packets (Ctrl-C to stop)
rx *args:
    @mise install --quiet && uv run {{source_directory()}}/simple_rx.py {{args}}

# Transmit a single packet
tx *args:
    @mise install --quiet && uv run {{source_directory()}}/simple_tx.py {{args}}

# Two-dongle ping-pong demo (--role tx|rx)
ping-pong *args:
    @mise install --quiet && uv run {{source_directory()}}/ping_pong.py {{args}}

# Exercise all DongLoRa commands
test-commands *args:
    @mise install --quiet && uv run {{source_directory()}}/all_commands.py {{args}}

# Two-way LoRa bridge over TCP
bridge *args:
    @mise install --quiet && uv run {{source_directory()}}/lora_bridge.py {{args}}

# MeshCore packet decoder/monitor
meshcore *args:
    @mise install --quiet && uv run {{source_directory()}}/meshcore/meshcore_rx.py {{args}}

# Run any example by name (e.g. just ex run simple_rx)
run script *args:
    @mise install --quiet && uv run {{source_directory()}}/{{script}}.py {{args}}
