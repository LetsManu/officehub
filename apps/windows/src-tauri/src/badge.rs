#![cfg_attr(not(windows), allow(dead_code))]
//! The number on the taskbar icon (Windows overlay icon): a red circle with white digits, drawn here.

/// 3×5 pixel digits, row by row (bit 2 = left column).
const DIGITS: [[u8; 5]; 11] = [
    [0b111, 0b101, 0b101, 0b101, 0b111], // 0
    [0b010, 0b110, 0b010, 0b010, 0b111], // 1
    [0b111, 0b001, 0b111, 0b100, 0b111], // 2
    [0b111, 0b001, 0b111, 0b001, 0b111], // 3
    [0b101, 0b101, 0b111, 0b001, 0b001], // 4
    [0b111, 0b100, 0b111, 0b001, 0b111], // 5
    [0b111, 0b100, 0b111, 0b101, 0b111], // 6
    [0b111, 0b001, 0b010, 0b010, 0b010], // 7
    [0b111, 0b101, 0b111, 0b101, 0b111], // 8
    [0b111, 0b101, 0b111, 0b001, 0b111], // 9
    [0b000, 0b010, 0b111, 0b010, 0b000], // +
];

const SIZE: usize = 32;

/// RGBA pixels of the badge for `count` (1–9, more shows "9+").
pub fn pixels(count: i64) -> Vec<u8> {
    let mut rgba = vec![0u8; SIZE * SIZE * 4];
    let center = (SIZE as f32 - 1.0) / 2.0;
    let radius = SIZE as f32 / 2.0;
    for y in 0..SIZE {
        for x in 0..SIZE {
            let d = ((x as f32 - center).powi(2) + (y as f32 - center).powi(2)).sqrt();
            let alpha = (radius - d).clamp(0.0, 1.0);
            let i = (y * SIZE + x) * 4;
            rgba[i] = 0xc4;
            rgba[i + 1] = 0x2b;
            rgba[i + 2] = 0x1c;
            rgba[i + 3] = (alpha * 255.0) as u8;
        }
    }
    let glyphs: Vec<usize> = if count > 9 { vec![9, 10] } else { vec![count.clamp(0, 9) as usize] };
    let scale = if glyphs.len() == 1 { 4 } else { 3 };
    let glyph_w = 3 * scale;
    let gap = scale;
    let total_w = glyphs.len() * glyph_w + (glyphs.len() - 1) * gap;
    let left = (SIZE - total_w) / 2;
    let top = (SIZE - 5 * scale) / 2;
    for (n, glyph) in glyphs.iter().enumerate() {
        let x0 = left + n * (glyph_w + gap);
        for (row, bits) in DIGITS[*glyph].iter().enumerate() {
            for col in 0..3 {
                if bits & (0b100 >> col) == 0 {
                    continue;
                }
                for dy in 0..scale {
                    for dx in 0..scale {
                        let (x, y) = (x0 + col * scale + dx, top + row * scale + dy);
                        let i = (y * SIZE + x) * 4;
                        rgba[i..i + 4].copy_from_slice(&[0xff, 0xff, 0xff, 0xff]);
                    }
                }
            }
        }
    }
    rgba
}

#[cfg(windows)]
pub fn image(count: i64) -> tauri::image::Image<'static> {
    tauri::image::Image::new_owned(pixels(count), SIZE as u32, SIZE as u32)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn badge_is_a_red_circle_with_white_digits() {
        let one = pixels(1);
        assert_eq!(one.len(), SIZE * SIZE * 4);
        // corner transparent, centre white (part of the digit or red)
        assert_eq!(one[3], 0);
        assert!(one.chunks(4).any(|p| p == [0xff, 0xff, 0xff, 0xff]));
        assert_ne!(pixels(12), pixels(9));
        assert_eq!(pixels(12), pixels(99)); // both "9+"
    }
}
