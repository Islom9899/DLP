"""
DMD pattern compression functions for DLPC900 controller.
Supports ERLE (Enhanced Run Length Encoding) and RLE compression.

Extracted from expt_ctrl/dlp6500.py - these functions are hardware-independent.
"""

import numpy as np


def combine_patterns(patterns: np.ndarray, bit_depth: int = 1):
    """
    Given a series of binary patterns, combine these into 24 bit RGB images to send to DMD.
    For binary patterns, the DMD supports sending a group of up to 24 patterns as an RGB image,
    with each bit of the 24 bit RGB values giving the pattern for one image.

    :param patterns: nimgs x ny x nx array of uint8
    :param bit_depth: 1
    :return combined_patterns:
    """

    if bit_depth != 1:
        raise NotImplementedError('not implemented')

    if not np.all(np.logical_or(patterns == 0, patterns == 1)):
        raise ValueError('patterns must be binary')

    combined_patterns = []
    n_combined_patterns = int(np.ceil(len(patterns) / 24))
    for num_pat in range(n_combined_patterns):

        combined_pattern_current = np.zeros((3, patterns.shape[1], patterns.shape[2]), dtype=np.uint8)

        for ii in range(np.min([24, len(patterns) - 24 * num_pat])):
            if ii < 8:
                combined_pattern_current[2, :, :] += patterns[ii + 24 * num_pat, :, :] * 2 ** ii
            elif ii >= 8 and ii < 16:
                combined_pattern_current[1, :, :] += patterns[ii + 24 * num_pat, :, :] * 2 ** (ii - 8)
            elif ii >= 16 and ii < 24:
                combined_pattern_current[0, :, :] += patterns[ii + 24 * num_pat, :, :] * 2 ** (ii - 16)

        combined_patterns.append(combined_pattern_current)

    return combined_patterns


def split_combined_patterns(combined_patterns) -> np.ndarray:
    """
    Split binary patterns which have been combined into a single uint8 RGB image back to separate images.

    :param combined_patterns: 3 x Ny x Nx uint8 array representing up to 24 combined patterns.
    :return: 24 x Ny x Nx array.
    """
    patterns = np.zeros((24,) + combined_patterns.shape[1:], dtype=np.uint8)

    for ii in range(8):
        patterns[ii] = (combined_patterns[2] & 2 ** ii) >> ii

    for ii in range(8, 16):
        patterns[ii] = (combined_patterns[1] & 2 ** (ii - 8)) >> (ii - 8)

    for ii in range(16, 24):
        patterns[ii] = (combined_patterns[0] & 2 ** (ii - 16)) >> (ii + 8)

    return patterns


def encode_erle(pattern: np.ndarray) -> list:
    """
    Encode a 24bit pattern in enhanced run length encoding (ERLE).

    specification:
    ctrl byte 1, ctrl byte 2, ctrl byte 3, description
    0          , 0          , n/a        , end of image
    0          , 1          , n          , copy n pixels from the same position on the previous line
    0          , n>1        , n/a        , n uncompressed RGB pixels follow
    n>1        , n/a        , n/a        , repeat following pixel n times

    :param pattern: uint8 3 x Ny x Nx array of RGB values, or Ny x Nx array
    :return pattern_compressed:
    """

    if pattern.dtype != np.uint8:
        raise ValueError('pattern must be of type uint8')

    if pattern.ndim == 2:
        pattern = np.concatenate((np.zeros((1,) + pattern.shape, dtype=np.uint8),
                                  np.zeros((1,) + pattern.shape, dtype=np.uint8),
                                  np.array(pattern[None, :, :], copy=True)), axis=0)

    if pattern.ndim != 3 and pattern.shape[0] != 3:
        raise ValueError("Image data is wrong shape. Must be 3 x ny x nx, with RGB values in each layer.")

    pattern_compressed = []
    _, ny, nx = pattern.shape

    for ii in range(pattern.shape[1]):
        row_rgb = pattern[:, ii, :]

        if ii > 0 and np.array_equal(row_rgb, pattern[:, ii - 1, :]):
            msb, lsb = erle_len2bytes(nx)
            pattern_compressed += [0x00, 0x01, msb, lsb]
        else:
            value_changed = np.sum(np.abs(np.diff(row_rgb, axis=1)), axis=0) != 0
            inds_change = np.concatenate((np.array([0]), np.where(value_changed)[0] + 1))

            run_lens = np.concatenate((np.array(inds_change[1:] - inds_change[:-1]),
                                       np.array([nx - inds_change[-1]])))

            for jj, rlen in zip(inds_change, run_lens):
                v = row_rgb[:, jj]
                length_bytes = erle_len2bytes(rlen)
                pattern_compressed += length_bytes + [v[0], v[1], v[2]]

    pattern_compressed += [0x00, 0x01, 0x00]

    return pattern_compressed


def encode_rle(pattern: np.ndarray) -> list:
    """
    Compress pattern using run length encoding (RLE).

    specification:
    ctrl byte 1, color byte, description
    0          , 0         , end of line
    0          , 1         , end of image (required)
    0          , n>=2      , n uncompressed RGB pixels follow
    n>0        , n/a       , repeat following RGB pixel n times

    :param pattern:
    :return pattern_compressed:
    """
    if pattern.dtype != np.uint8:
        raise ValueError('pattern must be of type uint8')

    if pattern.ndim == 2:
        pattern = np.concatenate((np.zeros((1,) + pattern.shape, dtype=np.uint8),
                                  np.zeros((1,) + pattern.shape, dtype=np.uint8),
                                  np.array(pattern[None, :, :], copy=True)), axis=0)

    if pattern.ndim != 3 and pattern.shape[0] != 3:
        raise ValueError("Image data is wrong shape. Must be 3 x ny x nx, with RGB values in each layer.")

    pattern_compressed = []
    _, ny, nx = pattern.shape

    for ii in range(pattern.shape[1]):
        row_rgb = pattern[:, ii, :]

        if ii > 0 and np.array_equal(row_rgb, pattern[:, ii - 1, :]):
            msb, lsb = erle_len2bytes(nx)
            pattern_compressed += [0x00, 0x01, msb, lsb]
        else:
            value_changed = np.sum(np.abs(np.diff(row_rgb, axis=1)), axis=0) != 0
            inds_change = np.concatenate((np.array([0]), np.where(value_changed)[0] + 1))

            run_lens = np.concatenate((np.array(inds_change[1:] - inds_change[:-1]),
                                       np.array([nx - inds_change[-1]])))

            for jj, rlen in zip(inds_change, run_lens):
                v = row_rgb[:, jj]
                if rlen <= 255:
                    pattern_compressed += [rlen, v[0], v[1], v[2]]
                else:
                    counter = 0
                    while counter < rlen:
                        end_pt = np.min([counter + 255, rlen]) - 1
                        current_len = end_pt - counter + 1
                        pattern_compressed += [current_len, v[0], v[1], v[2]]
                        counter = end_pt + 1

    pattern_compressed += [0x00]

    return pattern_compressed


def decode_erle(dmd_size, pattern_bytes: list):
    """
    Decode pattern from ERLE or RLE.

    :param dmd_size: [ny, nx]
    :param pattern_bytes: list of bytes representing encoded pattern
    :return rgb_pattern:
    """

    ii = 0
    line_no = 0
    line_pos = 0
    current_line = np.zeros((3, dmd_size[1]), dtype=np.uint8)
    rgb_pattern = np.zeros((3, 0, dmd_size[1]), dtype=np.uint8)

    while ii < len(pattern_bytes):

        if line_pos == dmd_size[1]:
            rgb_pattern = np.concatenate((rgb_pattern, current_line[:, None, :]), axis=1)
            current_line = np.zeros((3, dmd_size[1]), dtype=np.uint8)
            line_pos = 0
            line_no += 1
        elif line_pos >= dmd_size[1]:
            raise ValueError("While reading line %d, length of line exceeded expected value" % line_no)

        if ii == len(pattern_bytes) - 1:
            if pattern_bytes[ii] == 0:
                break
            else:
                raise ValueError('Image not terminated with 0x00')

        if pattern_bytes[ii] == 0:
            if pattern_bytes[ii + 1] == 0:
                ii += 1
                continue
            elif pattern_bytes[ii + 1] == 1:
                if pattern_bytes[ii + 2] < 128:
                    n_to_copy = pattern_bytes[ii + 2]
                    ii += 3
                else:
                    n_to_copy = erle_bytes2len(pattern_bytes[ii + 2:ii + 4])
                    ii += 4

                current_line[:, line_pos:line_pos + n_to_copy] = \
                    rgb_pattern[:, line_no - 1, line_pos:line_pos + n_to_copy]
                line_pos += n_to_copy
            else:
                if pattern_bytes[ii + 1] < 128:
                    n_unencoded = pattern_bytes[ii + 1]
                    ii += 2
                else:
                    n_unencoded = erle_bytes2len(pattern_bytes[ii + 1:ii + 3])
                    ii += 3

                for jj in range(n_unencoded):
                    current_line[0, line_pos + jj] = int(pattern_bytes[ii + 3 * jj])
                    current_line[1, line_pos + jj] = int(pattern_bytes[ii + 3 * jj + 1])
                    current_line[2, line_pos + jj] = int(pattern_bytes[ii + 3 * jj + 2])

                ii += 3 * n_unencoded
                line_pos += n_unencoded

            continue

        if pattern_bytes[ii] < 128:
            block_len = pattern_bytes[ii]
            ii += 1
        else:
            block_len = erle_bytes2len(pattern_bytes[ii:ii + 2])
            ii += 2

        current_line[0, line_pos:line_pos + block_len] = np.asarray([pattern_bytes[ii]] * block_len, dtype=np.uint8)
        current_line[1, line_pos:line_pos + block_len] = np.asarray([pattern_bytes[ii + 1]] * block_len, dtype=np.uint8)
        current_line[2, line_pos:line_pos + block_len] = np.asarray([pattern_bytes[ii + 2]] * block_len, dtype=np.uint8)
        ii += 3
        line_pos += block_len

    return rgb_pattern


def erle_len2bytes(length: int) -> list:
    """
    Encode a length between 0-2**15-1 as 1 or 2 bytes for use in erle encoding format.

    :param length: integer 0-(2**15-1)
    :return len_bytes:
    """

    if isinstance(length, float):
        if length.is_integer():
            length = int(length)
        else:
            raise TypeError('length must be convertible to integer.')

    if length < 0 or length > 2 ** 15 - 1:
        raise ValueError('length is negative or too large to be encoded.')

    if length < 128:
        len_bytes = [length]
    else:
        lsb = (length & 0x7F) | 0x80
        msb = length >> 7
        len_bytes = [lsb, msb]

    return len_bytes


def erle_bytes2len(byte_list: list) -> int:
    """
    Convert a 1 or 2 byte list in little endian order to length.
    :param list byte_list: [byte] or [lsb, msb]
    :return length:
    """

    if len(byte_list) == 1:
        length = byte_list[0]
    else:
        lsb, msb = byte_list
        length = (msb << 7) + (lsb - 0x80)

    return length
