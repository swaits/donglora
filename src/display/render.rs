use crate::channel::{RadioState, RadioStatus};

/// Render the status dashboard to a framebuffer.
///
/// Pure logic — no hardware dependency. Takes a status snapshot and produces
/// draw calls that the display task flushes to the screen.
pub fn dashboard(status: &RadioStatus) {
    // TODO: use embedded-graphics to render:
    //   Line 1: board name + radio state
    //   Line 2: freq / BW / SF
    //   Line 3: TX power / coding rate
    //   Line 4: RX count / TX count
    //   Line 5: last RSSI / SNR
    let _ = status;
}

/// Format radio state as a short display string.
#[allow(dead_code)]
pub fn state_label(state: RadioState) -> &'static str {
    match state {
        RadioState::Idle => "IDLE",
        RadioState::Receiving => "RX",
        RadioState::Transmitting => "TX",
    }
}
