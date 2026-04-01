set shell := ["bash", "-c"]

_proj := source_directory()
_uv := "uv run --project " + _proj
_uv_meshcore := "uv run --project " + _proj + " --extra meshcore"
_uv_orac := "uv run --project " + _proj + " --extra orac"

[private]
_ensure_tools:
    @mise trust --yes . 2>/dev/null; mise install --quiet

# Receive LoRa packets (Ctrl-C to stop)
rx *args: _ensure_tools
    @{{_uv}} {{source_directory()}}/simple_rx.py {{args}}

# Transmit a single packet
tx *args: _ensure_tools
    @{{_uv}} {{source_directory()}}/simple_tx.py {{args}}

# Two-dongle ping-pong demo (--role tx|rx)
ping-pong *args: _ensure_tools
    @{{_uv}} {{source_directory()}}/ping_pong.py {{args}}

# Exercise all DongLoRa commands
test-commands *args: _ensure_tools
    @{{_uv}} {{source_directory()}}/all_commands.py {{args}}

# Two-way LoRa bridge over TCP
bridge *args: _ensure_tools
    @{{_uv}} {{source_directory()}}/lora_bridge.py {{args}}

# MeshCore packet decoder/monitor
meshcore *args: _ensure_tools
    @{{_uv_meshcore}} {{source_directory()}}/meshcore/meshcore_rx.py {{args}}

# MeshCore AI bot (requires ANTHROPIC_API_KEY)
orac *args: _ensure_tools
    @{{_uv_orac}} {{source_directory()}}/meshcore/ai_bot.py {{args}}

# MeshCore repeater telemetry monitor
telemetry *args: _ensure_tools
    @{{_uv_meshcore}} {{source_directory()}}/meshcore/telemetry_monitor.py {{args}}
