## Module Naming & Structure

  1. The unified host communication module — do you prefer comm/, host/, or something else?

host/

  2. Should protocol.rs stay as a single file, or split into protocol/types.rs + protocol/framing.rs (absorbing protocol_io.rs)?

Split it apart logically

  3. Or should the framing code live inside the comm/ module since it's only used there?

You decide what makes the most sense based on our first principles

  4. The radio/ directory currently has just task.rs (and presumably a mod.rs). Should it stay a directory or flatten to radio.rs?

Flatten. No directory should ever have just one (or even 2?) things in it!

  5. Same question for display/ — it has task.rs, render.rs, and the driver. Keep as directory?

Nope. See previous question.

  6. Should there be a board/drivers/ subdirectory, or should the SH1106 driver just stay at the board level (e.g. board/sh1106.rs)?

Somehow, things like drivers need to be clearly separated from boards, both by
filename+location and by how the code is structured (abstractions, etc)

  7. The channel.rs file is standalone — is that fine, or should inter-task communication be grouped differently?

I guess fine?

  Board Definition Contract

  8. into_parts() is currently an inherent method, not on the trait. Should it be added to LoRaBoard (requires associated types), or is the implicit contract fine?

Nothing ever implicit. This is rust.

  9. Should we add a spawn_host_task() function to each board, or keep that concern in the comm/ module with internal cfg?

If it is going to vary by hardware, then yeah I think we have to push it down
into the board abstraction level. Which sucks, but at least so far seems to be
how it works. I frankly still don't believe that the Heltec V3 cannot be made to
look like a proper ttyACM0 device! I'm not giving up on that shit yet!!!

  10. Should boards export a single BoardParts struct (with radio, comm, display fields) instead of returning a tuple?

struct > tuple.

  11. Should LoRaBoard gain associated constants like const HAS_DISPLAY: bool or const COMM_TYPE: CommType?

I don't know. You can have a HTV4 with an OLED or without one. Does anything
above the board abstraction layer need to know this???

  12. Is the current LoRaBoard trait the right level of abstraction? Should it grow (more methods), shrink (fewer), or stay the same?

You decide.

  13. Should mac_address() remain on the trait, or become a field in a parts struct?

I think it can fit nicely in the struct. If that's a pattern we're choosing, be
consistent.

  14. The into_parts() currently consumes self (the Board). Is this the right ownership model?

I guess? Sounds rusty.

## Chip-Family Helpers

  15. For nrf52840.rs — should it be a single file or a directory (nrf52840/mod.rs + submodules)?

Maybe a directory? But how are we separating components from board
definitions??? I don't think we should just have one directory full of random
directories for MCUs, displays, UARTS, and boards all plopped in there. That
sounds **disorganized**, not **organized**.

  16. The nRF52840 bind_interrupts! macro — should it live in the helper or per-board? (Boards might use different peripherals.)

If you're **very** confident we'll need to customize it per-board, then go ahead
and break it out. If not, leave it generic across all boards.

  17. The mac_address() unsafe FICR block is identical in both nRF boards. Definitely extract to helper?

Yes.

  18. Both ESP32-S3 boards have identical Vext GPIO36 and display reset GPIO21 logic. Should this be in esp32s3.rs or per-board?

If you're confident this **will need to be board specific** before long, break
it out. Otherwise conslidate.

  19. Should chip family helpers define ALL possible init functions (USB, UART, etc.) even if not all boards use them, or only what's actually used?

Good question. I'm not sure. Best advice from you?

  20. Should esp32s3.rs be split into submodules (esp32s3/radio.rs, esp32s3/usb.rs, esp32s3/display.rs)?

Uhhhh.. and ESP32 is an MCU, not a radio, not a USB, not a display. GET THE
ABSTRACTIONS AND SEPARATION RIGHT!!!!!!!!!!!!!!!!!!!!!

  21. If we add an nrf52840.rs, should the existing esp32s3.rs be renamed for consistency (both are chip-family helpers but esp32s3 is named after the chip while nrf52840 would
   be named after the chip too — good)?

Make the naming scheme consistent.

## Display

  22. Should the board provide an already-initialized display (DisplayParts { display: DisplayDriver, mac }) or raw parts with a separate create_display() async function?

Board should provide the means to its consumer to init display, radio, etc. It
shouldn't preemptively init stuff.

  23. Since into_parts() is sync but display init is async — does the create_display() approach seem right?

I don't know. What's your advice?

  24. Do we need an AsyncDisplay trait (for flush + brightness), or is relying on the concrete type's methods via duck-typing sufficient?

What do you think?

  25. Both drivers implement DrawTarget — rendering is already generic. The only non-generic part is flush() and init(). Is pushing init/flush into the board layer the right call?

I think so.

  26. The SH1106 driver (display/sh1106.rs) — is it a hardware driver that belongs in board/drivers/, or display infrastructure that should stay in display/?

Think of the abstractions. Imagine you're just looking at this project for the
first time. Where would you look for a display driver??? drivers/? Something else?

  27. The display init retry logic (try twice, give up) is identical for both drivers. Should this be a common wrapper?

I think that retry is stupid. Let the client retry.

  28. Display brightness: SSD1306 uses Brightness::BRIGHTEST, SH1106 uses 0xFF. Should create_display() handle this internally?

Make it generic across displays.

  29. Currently display errors are silently ignored (let _ = display.flush().await). Is this intentional and should remain?

Seems like it should be elegantly handled and propagated up the abstraction layers.

## Host Communication

  30. USB has DTR disconnect detection that sends DisplayCommand::Reset/On. UART has no equivalent. Is it OK for UART boards to simply not have this feature?

I mean, do we have a choice? I **really** don't want to support these UART
boards. And I'm still refusing to believe that the Heltec V3's USB hardware
cannot be made to look like a proper ttyACM. People use these MCUs and boards to
create keyboards/HID and other things after all! So my REAL preference is to NOT
support these boards. That said, we have to support the Heltec V3. So, if we
can't do it properly, then I guess we don't have a choice here.

  31. The USB task runs join(usb_dev.run(), protocol_loop(...)) — UART just loops. Is having structurally different task bodies behind the same host_task name acceptable?

Consistency is important to me. I don't know the right answer here. But be
consistent and smart.

  32. Should comm/mod.rs compile ONLY the active transport, or compile both and let the linker dead-code-eliminate?

Umm if there's a nice way to do it, then sure. But no leaky abstractions! Use
traits and abstractions and layers so we compile the right thing for a given configuration.

  33. The USB task's COBS accumulation is inline and the UART task uses FrameAccumulator. I've verified they're semantically identical. Can I just replace the USB inline code with FrameAccumulator?

Sure. Is "FrameAccumulator" the right name for this though?

  34. The USB task's route_command (inline, lines 206-238) is byte-for-byte identical to protocol_io::route_command. Can I just delete the inline one?

Yes.

  35. MAX_FRAME is defined in both usb/task.rs (line 16) and protocol_io.rs (line 12). Should there be one canonical definition?

Yes.

## Build System

  36. How should build.rs discover chip-family helpers? Options: (a) scan board files for use super::<helper>, (b) naming convention, (c) explicit list in build.rs, (d) marker comments in board files?

I like build.rs scanning for board files. I just want them all in a logical
directory tree.

  37. The Jinja template approach — keep it, or is there something better?

I'm pretty happy with it. You tell me: is there something better???

  38. The justfile _info helper uses a hardcoded if/elif chain. Should this become data-driven (scan a file or Cargo.toml)?

Yes.

  39. Should the justfile board list at line 15 be auto-derived from Cargo.toml features?

Maybe. What if it's derived from the source files it finds?

  40. build.rs excludes mod, traits, esp32s3 from board discovery. With nrf52840.rs added, the exclusion list grows. Is a naming convention better (e.g.
  all-lowercase-with-underscores = board, CamelCase or chip-family-names = helper)?

"Exclustion lists" are evil. Fix the abstractions and design so we don't have to
deal with this shit.

## Future-Proofing

  41. Do ALL future boards use SX1262, or could there be SX1276/SX1280/other radios?

There will be other radios.

  42. Could a future board have NO display at all? (Currently all boards return Some(DisplayParts) or have optional display.)

Yes, many boards will have no display.

  43. Could a future board use SPI display instead of I2C?

Probably.

  44. Could a future board use a completely different MCU family (STM32, RP2040)?

Yes. In fact I have both STM and RP2040 boards sitting here now.

  45. Is there a realistic scenario where a board needs both USB AND UART?

No. FUCK UART.

  46. Could a future board need additional tasks beyond radio/comm/display (e.g. LED, sensor)?

I am thinking of adding an RGB LED interface down into the boards. Then if the
host has turned on the display, we'd blink the LED green anytime we receive and
red any time we transmit a packet.

And these boards often have lots of other hardware. Wi-Fi, BLE, sensors,
whatever. DongLoRa is really just about the radio though so I'm not prioritizing
supporting these, beyond the RGB LED thing I mentioned.

## Migration & Testing

  47. Should this be one atomic refactor, or phased (dedup first, then reorg, then display)? I propose phased — each step independently compilable and testable.

Probably phased. Use jj to checkpoint as you go along. When you're happy with a
phase, "jj commit -m 'WIP: phase description'" (jj commit is the same as a jj
describe + jj new)

  48. Are there any in-flight changes on other branches/bookmarks that would conflict?

Nope. We just finished getting the Heltec V3 to work, which are the last few
"WIP" commits.

  49. The protocol tests (just test) use DONGLORA_HOST_TEST=1 to skip build.rs board logic. Will the reorg affect this?

You tell me. What I do know is testing is extremely important. I'd like
comprehensive tests, property tests, mutation testing, fuzz testing. Basically
throw everything we have at it.

  50. After the reorg, do you want a CI-enforceable rule like "no #[cfg(feature = \"board_name\")] outside board/ and comm/mod.rs"?

That sounds great. Any mechanisms to enforce our abstractions and first
principles are very welcome.


BTW, NO unsafe code unless it is ABSOLUTELY REQUIRED. I know we're doing
embedded stuff. There are probably a few unsafe things we have to do. But always
research for ways to eliminate unsafe code.
