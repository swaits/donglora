use core::fmt::Write;

use embedded_graphics::mono_font::ascii::{FONT_6X10, FONT_9X15_BOLD};
use embedded_graphics::mono_font::MonoTextStyle;
use embedded_graphics::pixelcolor::BinaryColor;
use embedded_graphics::prelude::*;
use embedded_graphics::primitives::{Line, PrimitiveStyle, Rectangle};
use embedded_graphics::text::renderer::CharacterStyle;
use embedded_graphics::text::{Alignment, Text};
use heapless::String;

use crate::channel::{RadioState, RadioStatus};
use crate::protocol::Bandwidth;

/// RSSI ring buffer length — one bar per 2px across 128px.
pub const RSSI_HISTORY_LEN: usize = 64;

// Layout constants
const W: i32 = 128;
const FONT_H: i32 = 10;
const SEP_Y: i32 = 43;
const SPARK_TOP: i32 = 45;
const SPARK_H: i32 = 19; // y=45..63

// RSSI mapping range (dBm)
const RSSI_MIN: i16 = -120;
const RSSI_MAX: i16 = 0;

/// Render the boot splash screen.
pub fn splash(
    target: &mut impl DrawTarget<Color = BinaryColor>,
    board_name: &str,
    version: &str,
) {
    let _ = target.clear(BinaryColor::Off);

    let title_style = MonoTextStyle::new(&FONT_9X15_BOLD, BinaryColor::On);
    let sub_style = MonoTextStyle::new(&FONT_6X10, BinaryColor::On);

    Text::with_alignment("DongLoRa", Point::new(W / 2, 24), title_style, Alignment::Center)
        .draw(target)
        .ok();

    Text::with_alignment(version, Point::new(W / 2, 42), sub_style, Alignment::Center)
        .draw(target)
        .ok();

    Text::with_alignment(board_name, Point::new(W / 2, 54), sub_style, Alignment::Center)
        .draw(target)
        .ok();
}

/// Render the main status dashboard.
pub fn dashboard(
    target: &mut impl DrawTarget<Color = BinaryColor>,
    status: &RadioStatus,
    rssi_history: &[i16; RSSI_HISTORY_LEN],
    rssi_count: usize,
) {
    let _ = target.clear(BinaryColor::Off);
    let style = MonoTextStyle::new(&FONT_6X10, BinaryColor::On);

    match status.config {
        Some(cfg) => {
            // Row 0: state + frequency (full precision)
            let mut buf: String<32> = String::new();
            let state_str = match status.state {
                RadioState::Idle => "IDLE",
                RadioState::Receiving => "RX",
                RadioState::Transmitting => "TX",
            };
            let freq_mhz = cfg.freq_hz / 1_000_000;
            let freq_khz = (cfg.freq_hz % 1_000_000) / 1_000;
            let _ = write!(buf, "{:<4} {}.{:03}MHz", state_str, freq_mhz, freq_khz);
            Text::new(&buf, Point::new(0, FONT_H - 1), style)
                .draw(target)
                .ok();

            // Inverted state indicator when active
            if status.state != RadioState::Idle {
                let state_w = state_str.len() as i32 * 6;
                let mut inv_style = MonoTextStyle::new(&FONT_6X10, BinaryColor::Off);
                inv_style.set_background_color(Some(BinaryColor::On));
                Rectangle::new(Point::new(0, 0), Size::new(state_w as u32, FONT_H as u32))
                    .into_styled(PrimitiveStyle::with_fill(BinaryColor::On))
                    .draw(target)
                    .ok();
                Text::new(state_str, Point::new(0, FONT_H - 1), inv_style)
                    .draw(target)
                    .ok();
            }

            // Row 1: BW (full) SF CR
            buf.clear();
            let bw_str = match cfg.bw {
                Bandwidth::Khz7 => "7.8kHz",
                Bandwidth::Khz10 => "10.4kHz",
                Bandwidth::Khz15 => "15.6kHz",
                Bandwidth::Khz20 => "20.8kHz",
                Bandwidth::Khz31 => "31.2kHz",
                Bandwidth::Khz41 => "41.7kHz",
                Bandwidth::Khz62 => "62.5kHz",
                Bandwidth::Khz125 => "125kHz",
                Bandwidth::Khz250 => "250kHz",
                Bandwidth::Khz500 => "500kHz",
            };
            let _ = write!(buf, "{} SF{} CR4/{}", bw_str, cfg.sf, cr_denom(cfg.cr));
            Text::new(&buf, Point::new(0, FONT_H * 2 - 1), style)
                .draw(target)
                .ok();

            // Row 2: TX power + counters
            buf.clear();
            let _ = write!(
                buf,
                "{}dBm RX:{} TX:{}",
                cfg.tx_power_dbm, status.rx_count, status.tx_count
            );
            Text::new(&buf, Point::new(0, FONT_H * 3 - 1), style)
                .draw(target)
                .ok();

            // Row 3: RSSI + SNR
            buf.clear();
            match (status.last_rssi, status.last_snr) {
                (Some(rssi), Some(snr)) => {
                    let _ = write!(buf, "RSSI:{} dBm  SNR:{} dB", rssi, snr);
                }
                (Some(rssi), None) => {
                    let _ = write!(buf, "RSSI:{} dBm", rssi);
                }
                _ => {
                    let _ = write!(buf, "No signal");
                }
            }
            Text::new(&buf, Point::new(0, FONT_H * 4 - 1), style)
                .draw(target)
                .ok();

            // Separator line (moved down to give RSSI/SNR breathing room)
            Line::new(Point::new(0, SEP_Y), Point::new(W - 1, SEP_Y))
                .into_styled(PrimitiveStyle::with_stroke(BinaryColor::On, 1))
                .draw(target)
                .ok();

            // RSSI sparkline
            rssi_sparkline(target, rssi_history, rssi_count);
        }
        None => {
            Text::new("IDLE", Point::new(0, FONT_H - 1), style)
                .draw(target)
                .ok();
            Text::new("Waiting for host...", Point::new(0, FONT_H * 3 - 1), style)
                .draw(target)
                .ok();
        }
    }
}

/// Render the RSSI history as a bar-chart sparkline.
///
/// Each bar represents one time slot. The display task advances the
/// slot index on a fixed timer, so each bar covers a constant duration
/// regardless of packet rate. Bars with no packets in a slot show as empty.
fn rssi_sparkline(
    target: &mut impl DrawTarget<Color = BinaryColor>,
    history: &[i16; RSSI_HISTORY_LEN],
    count: usize,
) {
    if count == 0 {
        return;
    }

    let n = count.min(RSSI_HISTORY_LEN);
    let fill = PrimitiveStyle::with_fill(BinaryColor::On);

    for i in 0..n {
        let idx = if count <= RSSI_HISTORY_LEN {
            i
        } else {
            (count - RSSI_HISTORY_LEN + i) % RSSI_HISTORY_LEN
        };
        let rssi = history[idx];
        if rssi <= RSSI_MIN {
            continue; // empty slot
        }
        let clamped = rssi.clamp(RSSI_MIN, RSSI_MAX);

        let bar_h = ((clamped - RSSI_MIN) as i32 * SPARK_H) / (RSSI_MAX - RSSI_MIN) as i32;
        if bar_h == 0 {
            continue;
        }

        let x = (RSSI_HISTORY_LEN - n + i) as i32 * 2;
        let y = SPARK_TOP + SPARK_H - bar_h;

        Rectangle::new(Point::new(x, y), Size::new(2, bar_h as u32))
            .into_styled(fill)
            .draw(target)
            .ok();
    }
}

/// Clear the display (display-off state).
pub fn blank(target: &mut impl DrawTarget<Color = BinaryColor>) {
    let _ = target.clear(BinaryColor::Off);
}

fn cr_denom(cr: crate::protocol::CodingRate) -> u8 {
    use crate::protocol::CodingRate;
    match cr {
        CodingRate::Cr4_5 => 5,
        CodingRate::Cr4_6 => 6,
        CodingRate::Cr4_7 => 7,
        CodingRate::Cr4_8 => 8,
    }
}
