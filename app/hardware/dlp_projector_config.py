"""
DMD firmware configuration file I/O for DLPC900 controller.
Supports saving/loading pattern data, channel maps, and firmware patterns in zarr or json format.

Extracted from expt_ctrl/dlp6500.py - these functions are hardware-independent.
"""

from collections.abc import Sequence
from typing import Union, Optional
from copy import deepcopy
from pathlib import Path
from warnings import warn
import datetime
import json

import numpy as np

try:
    import zarr
    from numcodecs import packbits
except ImportError:
    zarr = None
    packbits = None


def validate_channel_map(cm: dict) -> tuple:
    """
    Check that channel_map is of the correct format.
    :param cm: dictionary defining channels
    :return success, message:
    """
    for ch in list(cm.keys()):
        modes = list(cm[ch].keys())

        if "default" not in modes:
            return False, f"'default' not present in channel '{ch:s}'"

        for m in modes:
            f_inds = cm[ch][m]
            if not isinstance(f_inds, (np.ndarray, list)):
                return False, f"firmware indices wrong type for channel '{ch:s}', mode '{m:s}'"

            if isinstance(f_inds, np.ndarray) and f_inds.ndim != 1:
                return False, f"firmware indices array with wrong dimension, '{ch:s}', mode '{m:s}'"

    return True, "array validated"


def save_config_file(fname: str,
                     pattern_data: Sequence[dict],
                     channel_map: Optional[dict] = None,
                     firmware_patterns: Optional[np.ndarray] = None,
                     hid_path: Optional[str] = None,
                     use_zarr: bool = True):
    """
    Save DMD firmware configuration data to zarr or json file.

    :param fname: file name to save
    :param pattern_data: list of dictionary objects with firmware pattern info
    :param channel_map: dictionary mapping modes to firmware indices
    :param firmware_patterns: npatterns x ny x nx array of patterns
    :param hid_path: HID device path
    :param use_zarr: whether to save as zarr or json
    """

    tstamp = datetime.datetime.now().strftime("%Y_%m_%d_%H;%M;%S")

    pattern_data_list = deepcopy(pattern_data)
    for p in pattern_data_list:
        for k, v in p.items():
            if isinstance(v, np.ndarray):
                p[k] = v.tolist()

    channel_map_list = None
    if channel_map is not None:
        valid, error = validate_channel_map(channel_map)
        if not valid:
            raise ValueError(f"channel_map validation failed with error '{error:s}'")

        channel_map_list = deepcopy(channel_map)
        for _, current_ch_dict in channel_map_list.items():
            for m, v in current_ch_dict.items():
                if isinstance(v, np.ndarray):
                    current_ch_dict[m] = v.tolist()

    if use_zarr:
        if zarr is None:
            raise ImportError("zarr is required for saving .zarr files. Install with: pip install zarr numcodecs")
        z = zarr.open(fname, "w")

        if firmware_patterns is not None:
            z.array("firmware_patterns",
                    firmware_patterns.astype(bool),
                    compressor=packbits.PackBits(),
                    dtype=bool,
                    chunks=(1, firmware_patterns.shape[-2], firmware_patterns.shape[-1]))

        z.attrs["timestamp"] = tstamp
        z.attrs["hid_path"] = hid_path
        z.attrs["firmware_pattern_data"] = pattern_data_list
        z.attrs["channel_map"] = channel_map_list

    else:
        if firmware_patterns is not None:
            warn("firmware_patterns were provided but json configuration file was selected."
                 " Use zarr instead to save firmware patterns")

        with open(fname, "w") as f:
            json.dump({"timestamp": tstamp,
                       "firmware_pattern_data": pattern_data_list,
                       "channel_map": channel_map_list,
                       "hid_path": hid_path}, f, indent="\t")


def load_config_file(fname: Union[str, Path]):
    """
    Load DMD firmware data from configuration file.

    :param fname: configuration file path
    :return pattern_data, channel_map, firmware_patterns, hid_path, tstamp:
    """

    fname = Path(fname)

    if fname.suffix == ".json":
        with open(fname, "r") as f:
            data = json.load(f)

        tstamp = data["timestamp"]
        pattern_data = data["firmware_pattern_data"]
        channel_map = data["channel_map"]
        firmware_patterns = None

        try:
            hid_path = data["hid_path"]
        except KeyError:
            hid_path = None

    elif fname.suffix == ".zarr":
        if zarr is None:
            raise ImportError("zarr is required for loading .zarr files. Install with: pip install zarr numcodecs")
        z = zarr.open(fname, "r")
        tstamp = z.attrs["timestamp"]
        pattern_data = z.attrs["firmware_pattern_data"]
        channel_map = z.attrs["channel_map"]

        try:
            hid_path = z.attrs["hid_path"]
        except KeyError:
            hid_path = None

        try:
            firmware_patterns = z["firmware_patterns"]
        except ValueError:
            firmware_patterns = None

    else:
        raise ValueError(f"fname suffix was '{fname.suffix:s}' but must be '.json' or '.zarr'")

    for p in pattern_data:
        for k, v in p.items():
            if isinstance(v, list) and len(v) > 1:
                p[k] = np.atleast_1d(v)

    if channel_map is not None:
        valid, error = validate_channel_map(channel_map)
        if not valid:
            raise ValueError(f"channel_map validation failed with error '{error:s}'")

        for ch, presets in channel_map.items():
            for mode_name, m in presets.items():
                presets[mode_name] = np.atleast_1d(m)

    return pattern_data, channel_map, firmware_patterns, hid_path, tstamp


def get_preset_info(inds: Sequence, pattern_data: Sequence[dict]) -> dict:
    """
    Get useful data from preset.

    :param inds: firmware pattern indices
    :param pattern_data: pattern data for each firmware pattern
    :return pd_all: aggregated pattern data dictionary
    """

    pd = [pattern_data[ii] for ii in inds]
    pd_all = {}
    for k in pd[0].keys():
        pd_all[k] = [p[k] for p in pd]

    return pd_all
