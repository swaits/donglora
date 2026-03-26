use crate::channel::RadioStatus;

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
