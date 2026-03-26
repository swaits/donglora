use embassy_executor::task;

use crate::board::DisplayParts;
use crate::channel::StatusWatch;

use super::render;

#[task]
pub async fn display_task(parts: DisplayParts, status: &'static StatusWatch) {
    let _i2c = parts.i2c;

    // TODO: init SSD1306 driver from I2C handle
    // TODO: initial render of empty dashboard

    let mut receiver = status.receiver().unwrap();

    loop {
        let state = receiver.changed().await;
        render::dashboard(&state);
        // TODO: flush framebuffer to display
    }
}
