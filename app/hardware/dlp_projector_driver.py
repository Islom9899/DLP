"""
DLP6500/DLP9000 DMD driver using hidapi for USB HID communication.
Refactored from expt_ctrl/dlp6500.py - pywinusb replaced with hidapi.

Only _get_device(), _send_raw_packet(), and __del__() are modified.
All other methods are identical to the original.
"""

from collections.abc import Sequence
from typing import Union, Optional
import sys
import time
from struct import pack, unpack
import numpy as np
from copy import deepcopy
from pathlib import Path
from warnings import warn

from .dlp_image_compression import combine_patterns, encode_erle, encode_rle
from .dlp_projector_config import load_config_file

try:
    import hid
except ImportError:
    hid = None
    warn("hidapi could not be imported. Install with: pip install hidapi")


class dlpc900_dmd:
    """
    Base class for communicating with any DMD using the DLPC900 controller,
    including the DLP6500 and DLP9000.
    Uses hidapi for cross-platform USB HID communication.
    """

    width = None
    height = None
    pitch = None
    dual_controller = None

    _dmd = None
    _packet_length_bytes = 64

    max_lut_index = 511
    min_time_us = 105
    _max_cmd_payload = 504

    dmd_type_code = {0: "unknown",
                     1: "DLP6500",
                     2: "DLP9000",
                     3: "DLP670S",
                     4: "DLP500YX",
                     5: "DLP5500"
                     }

    pattern_modes = {'video': 0x00,
                     'pre-stored': 0x01,
                     'video-pattern': 0x02,
                     'on-the-fly': 0x03
                     }

    compression_modes = {'none': 0x00,
                         'rle': 0x01,
                         'erle': 0x02
                         }

    command_dict = {'Read_Error_Code': 0x0100,
                    'Read_Error_Description': 0x0101,
                    'Get_Hardware_Status': 0x1A0A,
                    'Get_System_Status': 0x1A0B,
                    'Get_Main_Status': 0x1A0C,
                    'Get_Firmware_Version': 0x0205,
                    'Get_Firmware_Type': 0x0206,
                    'Get_Firmware_Batch_File_Name': 0x1A14,
                    'Execute_Firmware_Batch_File': 0x1A15,
                    'Set_Firmware_Batch_Command_Delay_Time': 0x1A16,
                    'PAT_START_STOP': 0x1A24,
                    'DISP_MODE': 0x1A1B,
                    'MBOX_DATA': 0x1A34,
                    'PAT_CONFIG': 0x1A31,
                    'PATMEM_LOAD_INIT_MASTER': 0x1A2A,
                    'PATMEM_LOAD_DATA_MASTER': 0x1A2B,
                    'PATMEM_LOAD_INIT_SECONDARY': 0x1A2C,
                    'PATMEM_LOAD_DATA_SECONDARY': 0x1A2D,
                    'TRIG_OUT1_CTL': 0x1A1D,
                    'TRIG_OUT2_CTL': 0x1A1E,
                    'TRIG_IN1_CTL': 0x1A35,
                    'TRIG_IN2_CTL': 0x1A36,
                    }

    err_dictionary = {0: 'no error',
                      1: 'batch file checksum error',
                      2: 'device failure',
                      3: 'invalid command number',
                      4: 'incompatible controller/dmd',
                      5: 'command not allowed in current mode',
                      6: 'invalid command parameter',
                      7: 'item referred by the parameter is not present',
                      8: 'out of resource (RAM/flash)',
                      9: 'invalid BMP compression type',
                      10: 'pattern bit number out of range',
                      11: 'pattern BMP not present in flash',
                      12: 'pattern dark time is out of range',
                      13: 'signal delay parameter is out of range',
                      14: 'pattern exposure time is out of range',
                      15: 'pattern number is out of range',
                      16: 'invalid pattern definition',
                      17: 'pattern image memory address is out of range',
                      255: 'internal error'
                      }

    status_strs = ['DMD micromirrors are parked',
                   'sequencer is running normally',
                   'video is frozen',
                   'external video source is locked',
                   'port 1 syncs valid',
                   'port 2 syncs valid',
                   'reserved',
                   'reserved'
                   ]

    hw_status_strs = ['internal initialization success',
                      'incompatible controller or DMD',
                      'DMD rest controller error',
                      'forced swap error',
                      'slave controller present',
                      'reserved',
                      'sequence abort status error',
                      'sequencer error'
                      ]

    def __init__(self,
                 vendor_id: int = 0x0451,
                 product_id: int = 0xc900,
                 debug: bool = True,
                 firmware_pattern_info: Optional[list] = None,
                 presets: Optional[dict] = None,
                 config_file: Optional[Union[str, Path]] = None,
                 firmware_patterns: Optional[np.ndarray] = None,
                 initialize: bool = True,
                 dmd_index: int = 0,
                 hid_path: Optional[bytes] = None,
                 platform: Optional[str] = None):
        """
        Get instance of DLP LightCrafter evaluation module (DLP6500 or DLP9000).

        :param vendor_id: vendor id (default 0x0451 for TI)
        :param product_id: product id (default 0xc900 for DLPC900)
        :param debug: print command output
        :param firmware_pattern_info: list of pattern info dicts
        :param presets: dictionary of presets
        :param config_file: path to config file (.json or .zarr)
        :param firmware_patterns: npatterns x ny x nx array
        :param initialize: whether to connect to DMD immediately
        :param dmd_index: which DMD to use if multiple are connected
        :param hid_path: specific HID device path (bytes)
        :param platform: override platform detection
        """

        if config_file is not None and (firmware_pattern_info is not None or
                                        presets is not None or
                                        firmware_patterns is not None):
            raise ValueError("both config_file and either firmware_pattern_info, presets, or firmware_patterns"
                             " were provided. But if config file is provided, these other settings should not be"
                             " set directly.")

        if config_file is not None:
            firmware_pattern_info, presets, firmware_patterns, hid_path_config, _ = load_config_file(config_file)

            if hid_path_config is not None:
                if hid_path is not None:
                    warn("hid_path was provided as argument, so value loaded from configuration file will be ignored")
                else:
                    hid_path = hid_path_config

        if firmware_pattern_info is None:
            firmware_pattern_info = []

        if presets is None:
            presets = {}

        if firmware_patterns is not None:
            firmware_patterns = np.array(firmware_patterns)
            self.firmware_indices = np.arange(len(firmware_patterns))
        else:
            self.firmware_indices = None

        self.firmware_pattern_info = firmware_pattern_info
        self.presets = presets
        self.firmware_patterns = firmware_patterns
        self.on_the_fly_patterns = None

        self.debug = debug

        self.vendor_id = vendor_id
        self.product_id = product_id
        self.dmd_index = dmd_index
        self._hid_path = hid_path

        if platform is None:
            self._platform = sys.platform
        else:
            self._platform = platform

        self.initialized = initialize
        if self.initialized:
            self._get_device()

    def __del__(self):
        try:
            if self._dmd is not None:
                self._dmd.close()
        except Exception:
            pass

    def initialize(self, **kwargs):
        self.__init__(initialize=True, **kwargs)

    # =========================================================================
    # USB HID communication (hidapi)
    # =========================================================================
    def _get_device(self):
        """
        Open USB HID connection to DMD using hidapi.
        """

        if hid is None:
            raise ImportError("hidapi is not installed. Install with: pip install hidapi")

        if self._platform == "none":
            return

        if self._hid_path is not None:
            # Open by specific HID path
            path = self._hid_path
            if isinstance(path, str):
                path = path.encode()
            self._dmd = hid.device()
            self._dmd.open_path(path)
        else:
            # Enumerate and find DLPC900 devices
            all_devices = hid.enumerate(self.vendor_id, self.product_id)
            dlpc900_devices = [d for d in all_devices if d['product_string'] == 'DLPC900']

            if len(dlpc900_devices) == 0:
                raise ConnectionError(
                    f"No DLPC900 devices found (VID=0x{self.vendor_id:04X}, PID=0x{self.product_id:04X}). "
                    f"Check USB connection and drivers."
                )

            if len(dlpc900_devices) <= self.dmd_index:
                raise ValueError(
                    f"Not enough DMD's detected for dmd_index={self.dmd_index:d}. "
                    f"Only {len(dlpc900_devices):d} DMD's were detected."
                )

            device_info = dlpc900_devices[self.dmd_index]
            self._hid_path = device_info['path']
            self._dmd = hid.device()
            self._dmd.open_path(self._hid_path)

        # Set blocking mode for reads
        self._dmd.set_nonblocking(0)

    def _send_raw_packet(self,
                         buffer,
                         listen_for_reply: bool = False,
                         timeout: float = 5):
        """
        Send a single USB packet via hidapi and optionally read reply.

        :param buffer: list of bytes to send (must be _packet_length_bytes long)
        :param listen_for_reply: whether to read a reply
        :param timeout: timeout in seconds
        :return reply: list of bytes
        """

        assert len(buffer) == self._packet_length_bytes

        # hidapi write() expects report ID as first byte
        report = bytes([0x00] + buffer)
        self._dmd.write(report)

        reply = []
        if listen_for_reply:
            timeout_ms = int(timeout * 1000)
            # hidapi read() returns data without report ID
            data = self._dmd.read(self._packet_length_bytes, timeout_ms)
            if data:
                reply = list(data)
            else:
                print('read command timed out')

        return reply

    # =========================================================================
    # Command protocol (unchanged from original)
    # =========================================================================
    def send_raw_command(self,
                         buffer,
                         listen_for_reply: bool = False,
                         timeout: float = 5):
        """
        Send a raw command over USB, possibly including multiple packets.

        :param buffer: buffer to send. List of bytes.
        :param listen_for_reply: whether to wait for reply
        :param timeout: time to wait for reply, in seconds
        :return reply: list of bytes
        """

        reply = []
        data_counter = 0
        while data_counter < len(buffer):

            data_counter_next = data_counter + self._packet_length_bytes
            data_to_send = buffer[data_counter:data_counter_next]

            if len(data_to_send) < self._packet_length_bytes:
                data_to_send += [0x00] * (self._packet_length_bytes - len(data_to_send))

            packet_reply = self._send_raw_packet(data_to_send, listen_for_reply, timeout)
            reply += packet_reply

            data_counter = data_counter_next

        return reply

    def send_command(self,
                     rw_mode: str,
                     reply: bool,
                     command: int,
                     data=(),
                     sequence_byte=0x00):
        """
        Send USB command to DMD.

        :param rw_mode: 'r' for read, or 'w' for write
        :param reply: boolean
        :param command: two byte integer
        :param data: data to be transmitted
        :param sequence_byte: integer
        :return response_buffer:
        """

        flagstring = ''
        if rw_mode == 'r':
            flagstring += '1'
        elif rw_mode == 'w':
            flagstring += '0'
        else:
            raise ValueError("flagstring should be 'r' or 'w' but was '%s'" % flagstring)

        if reply:
            flagstring += '1'
        else:
            flagstring += '0'

        flagstring += '0'
        flagstring += '00'
        flagstring += '000'

        flag_byte = int(flagstring, 2)

        len_payload = len(data) + 2
        len_lsb, len_msb = unpack('BB', pack('H', len_payload))

        cmd_lsb, cmd_msb = unpack('BB', pack('H', command))

        header = [flag_byte, sequence_byte, len_lsb, len_msb, cmd_lsb, cmd_msb]
        buffer = header + list(data)

        if self.debug:
            print('header: ' + bin(header[0]), end=' ')
            for ii in range(1, len(header)):
                print("0x%0.2X" % header[ii], end=' ')
            print('')

            for k, v in self.command_dict.items():
                if v == command:
                    print(k + " (" + hex(command) + ") :", end=' ')
                    break

            for d in data:
                print("0x%0.2X" % d, end=' ')
            print('')

        response_buffer = self.send_raw_command(buffer,
                                                listen_for_reply=reply)

        if self.debug:
            if reply:
                try:
                    resp = self.decode_response(response_buffer)
                    print("response = ", resp)
                except (ValueError, IndexError):
                    print("response = ", response_buffer)
            print('')

        return response_buffer

    @staticmethod
    def decode_command(buffer, is_first_packet: bool = True):
        """
        Decode DMD command into constituent pieces.
        """

        if is_first_packet:
            flag_byte = bin(buffer[1])
            sequence_byte = hex(buffer[2])
            len_bytes = pack('B', buffer[4]) + pack('B', buffer[3])
            data_len = unpack('H', len_bytes)[0]
            cmd = pack('B', buffer[6]) + pack('B', buffer[5])
            data = buffer[7:]
        else:
            flag_byte = None
            sequence_byte = None
            data_len = None
            cmd = None
            data = buffer[1:]

        return flag_byte, sequence_byte, data_len, cmd, data

    @staticmethod
    def decode_flag_byte(flag_byte) -> dict:
        """
        Get parameters from flags set in the flag byte.
        """

        errs = [2 ** ii & flag_byte != 0 for ii in range(5, 8)]
        err_names = ['error', 'host requests reply', 'read transaction']
        result = {}
        for e, en in zip(errs, err_names):
            result[en] = e

        return result

    def decode_response(self, buffer) -> dict:
        """
        Parse USB response from DMD into useful info.
        """

        if buffer == []:
            raise ValueError("buffer was empty")

        flag_byte = buffer[0]
        response = self.decode_flag_byte(flag_byte)

        sequence_byte = buffer[1]

        len_bytes = pack('B', buffer[2]) + pack('B', buffer[3])
        data_len = unpack('<H', len_bytes)[0]

        data = buffer[4:4 + data_len]

        response.update({'sequence byte': sequence_byte, 'data': data})

        return response

    # =========================================================================
    # DMD info queries
    # =========================================================================
    def read_error_code(self) -> tuple:
        """Retrieve error code number from last executed command."""

        buffer = self.send_command('w', True, self.command_dict["Read_Error_Code"])
        resp = self.decode_response(buffer)
        if len(resp["data"]) > 0:
            err_code = resp['data'][0]
        else:
            err_code = None

        try:
            error_type = self.err_dictionary[err_code]
        except KeyError:
            error_type = 'not defined'

        return error_type, err_code

    def read_error_description(self) -> str:
        """Retrieve error code description for the last error."""

        buffer = self.send_command('r', True, self.command_dict["Read_Error_Description"])
        resp = self.decode_response(buffer)

        err_description = ''
        for ii, d in enumerate(resp['data']):
            if d == 0:
                break
            err_description += chr(d)

        return err_description

    def get_hw_status(self) -> dict:
        """Get hardware status of DMD."""

        buffer = self.send_command('r', True, self.command_dict["Get_Hardware_Status"])
        resp = self.decode_response(buffer)

        errs = [(2 ** ii & resp['data'][0]) != 0 for ii in range(8)]

        result = {}
        for e, en in zip(errs, self.hw_status_strs):
            result[en] = e

        return result

    def get_system_status(self) -> dict:
        """Get status of internal memory test."""

        buffer = self.send_command('r', True, self.command_dict["Get_System_Status"])
        resp = self.decode_response(buffer)

        return {'internal memory test passed': bool(resp['data'][0])}

    def get_main_status(self) -> dict:
        """Get DMD main status."""

        buffer = self.send_command('r', True, self.command_dict["Get_Main_Status"])
        resp = self.decode_response(buffer)

        errs = [2 ** ii & resp['data'][0] != 0 for ii in range(8)]

        result = {}
        for e, en in zip(errs, self.status_strs):
            result[en] = e

        return result

    def get_firmware_version(self) -> dict:
        """Get firmware version information from DMD."""

        buffer = self.send_command('r', True, self.command_dict["Get_Firmware_Version"])
        resp = self.decode_response(buffer)

        app_version = resp['data'][0:4]
        app_patch = unpack('<H', b"".join([b.to_bytes(1, 'big') for b in app_version[0:2]]))[0]
        app_minor = app_version[2]
        app_major = app_version[3]
        app_version_str = '%d.%d.%d' % (app_major, app_minor, app_patch)

        api_version = resp['data'][4:8]
        api_patch = unpack('<H', b"".join([b.to_bytes(1, 'big') for b in api_version[0:2]]))[0]
        api_minor = api_version[2]
        api_major = api_version[3]
        api_version_str = '%d.%d.%d' % (api_major, api_minor, api_patch)

        software_config_revision = resp['data'][8:12]
        swc_patch = unpack('<H', b"".join([b.to_bytes(1, 'big') for b in software_config_revision[0:2]]))[0]
        swc_minor = software_config_revision[2]
        swc_major = software_config_revision[3]
        swc_version_str = '%d.%d.%d' % (swc_major, swc_minor, swc_patch)

        sequencer_config_revision = resp['data'][12:16]
        sqc_patch = unpack('<H', b"".join([b.to_bytes(1, 'big') for b in sequencer_config_revision[0:2]]))[0]
        sqc_minor = sequencer_config_revision[2]
        sqc_major = sequencer_config_revision[3]
        sqc_version_str = '%d.%d.%d' % (sqc_major, sqc_minor, sqc_patch)

        result = {'app version': app_version_str,
                  'api version': api_version_str,
                  'software configuration revision': swc_version_str,
                  'sequence configuration revision': sqc_version_str}

        return result

    def get_firmware_type(self) -> dict:
        """Get DMD type and firmware tag."""

        buffer = self.send_command('r', True, self.command_dict["Get_Firmware_Type"])
        resp = self.decode_response(buffer)

        dmd_type_flag = resp['data'][0]
        try:
            dmd_type = self.dmd_type_code[dmd_type_flag]
        except KeyError:
            raise ValueError(f"Unknown DMD type index {dmd_type_flag:d}. "
                             f"Allowed values are {self.dmd_type_code}")

        firmware_tag = ''
        for d in resp['data'][1:]:
            if d == 0:
                break
            firmware_tag += chr(d)

        return {'dmd type': dmd_type, 'firmware tag': firmware_tag}

    # =========================================================================
    # Trigger setup
    # =========================================================================
    def set_trigger_out(self,
                        trigger_number: int = 1,
                        invert: bool = False,
                        rising_edge_delay_us: int = 0,
                        falling_edge_delay_us: int = 0):
        """
        Set DMD output trigger delays and polarity.
        Trigger 1 is "advance frame", trigger 2 is "enable".
        """

        if rising_edge_delay_us < -20 or rising_edge_delay_us > 20e3:
            raise ValueError('rising edge delay must be in range -20 -- 20000us')

        if falling_edge_delay_us < -20 or falling_edge_delay_us > 20e3:
            raise ValueError('falling edge delay must be in range -20 -- 20000us')

        if invert:
            assert rising_edge_delay_us >= falling_edge_delay_us

        trig_byte = [int(invert)]
        rising_edge_bytes = unpack('BB', pack('<h', rising_edge_delay_us))
        falling_edge_bytes = unpack('BB', pack('<h', falling_edge_delay_us))
        data = trig_byte + list(rising_edge_bytes) + list(falling_edge_bytes)

        if trigger_number == 1:
            resp = self.send_command('w', True, self.command_dict["TRIG_OUT1_CTL"], data)
        elif trigger_number == 2:
            resp = self.send_command('w', True, self.command_dict["TRIG_OUT2_CTL"], data)
        else:
            raise ValueError('trigger_number must be 1 or 2')

        return resp

    def get_trigger_in1(self):
        """Query information about trigger 1 ("advance frame" trigger)."""

        buffer = self.send_command('r', True, self.command_dict["TRIG_IN1_CTL"], [])
        resp = self.decode_response(buffer)
        data = resp['data']
        delay_us, = unpack('<H', pack('B', data[0]) + pack('B', data[1]))
        mode = data[2]

        return delay_us, mode

    def set_trigger_in1(self,
                        delay_us: int = 105,
                        edge_to_advance: str = 'rising'):
        """
        Set delay and pattern advance edge for trigger input 1.
        """

        if delay_us < 104:
            raise ValueError(f'delay time must be {self.min_time_us:.0f}us or longer.')

        delay_byte = list(unpack('BB', pack('<H', delay_us)))

        if edge_to_advance == 'rising':
            advance_byte = [0x00]
        elif edge_to_advance == 'falling':
            advance_byte = [0x01]
        else:
            raise ValueError("edge_to_advance must be 'rising' or 'falling', but was '%s'" % edge_to_advance)

        return self.send_command('w', True, self.command_dict["TRIG_IN1_CTL"], delay_byte + advance_byte)

    def get_trigger_in2(self):
        """Query polarity of trigger in 2 ("enable" trigger)."""

        buffer = self.send_command('r', True, self.command_dict["TRIG_IN2_CTL"], [])
        resp = self.decode_response(buffer)
        mode = resp['data'][0]
        return mode

    def set_trigger_in2(self, edge_to_start: str = 'rising'):
        """Set polarity to start/stop pattern on for input trigger 2."""

        if edge_to_start == 'rising':
            start_byte = [0x00]
        elif edge_to_start == 'falling':
            start_byte = [0x01]
        else:
            raise ValueError("edge_to_start must be 'rising' or 'falling', but was '%s'" % edge_to_start)

        return self.send_command('w', False, self.command_dict["TRIG_IN2_CTL"], start_byte)

    # =========================================================================
    # Pattern mode control
    # =========================================================================
    def set_pattern_mode(self, mode: str = 'on-the-fly'):
        """
        Change the DMD display mode.
        :param mode: 'video', 'pre-stored', 'video-pattern', or 'on-the-fly'
        """
        if mode not in self.pattern_modes.keys():
            raise ValueError(f"mode was '{mode:s}', but the only supported values are {self.pattern_modes}")

        data = [self.pattern_modes[mode]]
        return self.send_command('w', True, self.command_dict["DISP_MODE"], data)

    def start_stop_sequence(self, cmd: str):
        """
        Start, stop, or pause a pattern sequence.
        :param cmd: 'start', 'stop' or 'pause'
        """
        if cmd == 'start':
            data = [0x02]
            seq_byte = 0x08
        elif cmd == 'stop':
            data = [0x00]
            seq_byte = 0x05
        elif cmd == 'pause':
            data = [0x01]
            seq_byte = 0x00
        else:
            raise ValueError(f"cmd must be 'start', 'stop', or 'pause', but was '{cmd:s}'")

        return self.send_command('w', False, self.command_dict["PAT_START_STOP"], data, sequence_byte=seq_byte)

    # =========================================================================
    # Firmware batch files
    # =========================================================================
    def get_fwbatch_name(self, batch_index: int) -> str:
        """Return name of batch file stored on firmware at batch_index."""

        buffer = self.send_command('r', True, self.command_dict["Get_Firmware_Batch_File_Name"], [batch_index])
        resp = self.decode_response(buffer)

        batch_name = ''
        for ii, d in enumerate(resp['data']):
            if d == 0:
                break
            batch_name += chr(d)

        return batch_name

    def execute_fwbatch(self, batch_index: int):
        """Execute batch file stored on firmware at index batch_index."""
        return self.send_command('w', True, self.command_dict["Execute_Firmware_Batch_File"], [batch_index])

    # =========================================================================
    # Low-level pattern commands
    # =========================================================================
    def _pattern_display_lut_configuration(self,
                                           num_patterns: int,
                                           num_repeat: int = 0):
        """
        Controls the execution of patterns stored in the lookup table (LUT).
        """
        if num_patterns > self.max_lut_index:
            raise ValueError(f"num_patterns must be <= {self.max_lut_index:d} but was {num_patterns:d}")

        num_patterns_bytes = list(unpack('BB', pack('<H', num_patterns)))
        num_repeats_bytes = list(unpack('BBBB', pack('<I', num_repeat)))

        return self.send_command('w', True, self.command_dict["PAT_CONFIG"],
                                 data=num_patterns_bytes + num_repeats_bytes)

    def _pattern_display_lut_definition(self,
                                        sequence_position_index: int,
                                        exposure_time_us: int = 105,
                                        dark_time_us: int = 0,
                                        wait_for_trigger: bool = True,
                                        clear_pattern_after_trigger: bool = False,
                                        bit_depth: int = 1,
                                        disable_trig_2: bool = True,
                                        stored_image_index: int = 0,
                                        stored_image_bit_index: int = 0):
        """
        Define parameters for pattern used in on-the-fly mode (MBOX_DATA).
        """

        pattern_index_bytes = list(unpack('BB', pack('<H', sequence_position_index)))
        exposure_bytes = list(unpack('BBBB', pack('<I', exposure_time_us)))[:-1]

        misc_byte_str = ''
        if clear_pattern_after_trigger:
            misc_byte_str += '1'
        else:
            misc_byte_str += '0'

        if bit_depth != 1:
            raise NotImplementedError('bit_depths other than 1 not implemented.')
        misc_byte_str += '000'

        misc_byte_str += '100'

        if wait_for_trigger:
            misc_byte_str += '1'
        else:
            misc_byte_str += '0'

        misc_byte = [int(misc_byte_str[::-1], 2)]

        dark_time_bytes = list(unpack('BB', pack('<H', dark_time_us))) + [0]
        if disable_trig_2:
            trig2_output_bytes = [0x00]
        else:
            trig2_output_bytes = [0x01]

        img_pattern_index_byte = [stored_image_index]
        pattern_bit_index_byte = [8 * stored_image_bit_index]

        data = pattern_index_bytes + exposure_bytes + misc_byte + \
               dark_time_bytes + trig2_output_bytes + img_pattern_index_byte + pattern_bit_index_byte

        return self.send_command('w', True, self.command_dict["MBOX_DATA"], data)

    def _init_pattern_bmp_load(self,
                               pattern_length: int,
                               pattern_index: int,
                               primary_controller: bool = True):
        """
        Initialize pattern BMP load command (PATMEM_LOAD_INIT_MASTER).
        Images should be loaded in reverse order.
        """

        index_bin = list(unpack('BB', pack('<H', pattern_index)))
        num_bytes = list(unpack('BBBB', pack('<I', pattern_length)))
        data = index_bin + num_bytes

        if primary_controller:
            cmd = self.command_dict["PATMEM_LOAD_INIT_MASTER"]
        else:
            cmd = self.command_dict["PATMEM_LOAD_INIT_SECONDARY"]

        return self.send_command('w', True, cmd, data=data)

    def _pattern_bmp_load(self,
                          compressed_pattern: list,
                          compression_mode: str,
                          pattern_index: int = 0,
                          primary_controller: bool = True):
        """
        Load DMD pattern data for use in pattern on-the-fly mode (PATMEM_LOAD_DATA_MASTER).
        """

        if self.dual_controller:
            width = self.width // 2
        else:
            width = self.width

        # 48-byte header
        signature_bytes = [0x53, 0x70, 0x6C, 0x64]
        width_byte = list(unpack('BB', pack('<H', width)))
        height_byte = list(unpack('BB', pack('<H', self.height)))
        num_encoded_bytes = list(unpack('BBBB', pack('<I', len(compressed_pattern))))
        reserved_bytes = [0xFF] * 8
        bg_color_bytes = [0x00] * 4

        if compression_mode not in self.compression_modes.keys():
            raise ValueError(f"compression_mode was '{compression_mode:s}', "
                             f"but must be one of {self.compression_modes.keys()}")
        encoding_byte = [self.compression_modes[compression_mode]]

        general_data = signature_bytes + width_byte + height_byte + num_encoded_bytes + \
                       reserved_bytes + bg_color_bytes + [0x01] + encoding_byte + \
                       [0x01] + [0x00] * 2 + [0x01] + [0x00] * 18

        data = general_data + compressed_pattern

        buffer = self._init_pattern_bmp_load(len(compressed_pattern) + 48,
                                             pattern_index=pattern_index,
                                             primary_controller=primary_controller)
        resp = self.decode_response(buffer)
        if resp['error']:
            print(self.read_error_description())

        if primary_controller:
            cmd = self.command_dict["PATMEM_LOAD_DATA_MASTER"]
        else:
            cmd = self.command_dict["PATMEM_LOAD_DATA_SECONDARY"]

        data_index = 0
        while data_index < len(data):
            data_index_next = np.min([data_index + self._max_cmd_payload, len(data)])
            data_current = data[data_index:data_index_next]

            data_len_bytes = list(unpack('BB', pack('<H', len(data_current))))

            self.send_command('w', False, cmd, data=data_len_bytes + data_current)

            data_index = data_index_next

    # =========================================================================
    # High-level pattern upload
    # =========================================================================
    def upload_pattern_sequence(self,
                                patterns: np.ndarray,
                                exp_times: Optional[Union[Sequence[int], int]] = None,
                                dark_times: Optional[Union[Sequence[int], int]] = 0,
                                triggered: bool = False,
                                clear_pattern_after_trigger: bool = False,
                                bit_depth: int = 1,
                                num_repeats: int = 0,
                                compression_mode: str = 'erle'):
        """
        Upload on-the-fly pattern sequence to DMD.

        :param patterns: N x Ny x Nx NumPy array of uint8
        :param exp_times: exposure times in us (>= min_time_us)
        :param dark_times: dark times in us
        :param triggered: wait for advance frame trigger
        :param clear_pattern_after_trigger: clear DMD after exp_time
        :param bit_depth: bit depth of patterns
        :param num_repeats: 0 = infinite
        :param compression_mode: 'erle', 'rle', or 'none'
        """

        if patterns.dtype != np.uint8:
            raise ValueError('patterns must be of dtype uint8')

        if patterns.ndim == 2:
            patterns = np.expand_dims(patterns, axis=0)

        npatterns = len(patterns)

        if exp_times is None:
            exp_times = self.min_time_us

        if not isinstance(exp_times, (list, np.ndarray)):
            exp_times = [exp_times]

        if not all(list(map(lambda t: isinstance(t, int), exp_times))):
            raise ValueError("exp_times must be a list of integers")

        if patterns.shape[0] > 1 and len(exp_times) == 1:
            exp_times = exp_times * patterns.shape[0]

        if isinstance(dark_times, int):
            dark_times = [dark_times]

        if not all(list(map(lambda t: isinstance(t, int), dark_times))):
            raise ValueError("dark_times must be a list of integers")

        if patterns.shape[0] > 1 and len(dark_times) == 1:
            dark_times = dark_times * patterns.shape[0]

        if compression_mode not in self.compression_modes.keys():
            raise ValueError(f"compression mode was '{compression_mode:s}', "
                             f"but must be one of {self.compression_modes.keys()}")

        if compression_mode != "erle":
            raise NotImplementedError("Currently only `erle` compression is implemented")

        if compression_mode == 'none':
            def compression_fn(p): return np.packbits(p.ravel())
        elif compression_mode == 'rle':
            compression_fn = encode_rle
        elif compression_mode == 'erle':
            compression_fn = encode_erle

        self.on_the_fly_patterns = patterns

        self.start_stop_sequence('stop')

        buffer = self.set_pattern_mode('on-the-fly')
        resp = self.decode_response(buffer)
        if resp['error']:
            print(self.read_error_description())

        self.start_stop_sequence('stop')

        for ii, (p, et, dt) in enumerate(zip(patterns, exp_times, dark_times)):
            pic_ind, bit_ind = self._index_2pic_bit(ii)
            buffer = self._pattern_display_lut_definition(ii,
                                                          exposure_time_us=et,
                                                          dark_time_us=dt,
                                                          wait_for_trigger=triggered,
                                                          clear_pattern_after_trigger=clear_pattern_after_trigger,
                                                          bit_depth=bit_depth,
                                                          stored_image_index=pic_ind,
                                                          stored_image_bit_index=bit_ind)
            resp = self.decode_response(buffer)
            if resp['error']:
                print(self.read_error_description())

        buffer = self._pattern_display_lut_configuration(npatterns, num_repeats)
        resp = self.decode_response(buffer)
        if resp['error']:
            print(self.read_error_description())

        if bit_depth == 1:
            patterns = combine_patterns(patterns)
        else:
            raise NotImplementedError("Combining multiple images into a 24-bit RGB image is only"
                                      " implemented for bit depth 1.")

        for ii, dmd_pattern in reversed(list(enumerate(patterns))):
            if self.debug:
                print(f"sending pattern {ii + 1:d}/{len(patterns):d}")

            if self.dual_controller:
                p0, p1 = np.array_split(dmd_pattern, 2, axis=-1)
                cp0 = compression_fn(p0)
                cp1 = compression_fn(p1)
                self._pattern_bmp_load(cp0, compression_mode, pattern_index=ii, primary_controller=True)
                self._pattern_bmp_load(cp1, compression_mode, pattern_index=ii, primary_controller=False)
            else:
                compressed_pattern = compression_fn(dmd_pattern)
                self._pattern_bmp_load(compressed_pattern, compression_mode,
                                       pattern_index=ii, primary_controller=True)

        buffer = self._pattern_display_lut_configuration(npatterns, num_repeats)
        resp = self.decode_response(buffer)
        if resp['error']:
            print(self.read_error_description())

        self.start_stop_sequence('start')

        if triggered:
            self.start_stop_sequence('stop')

    def set_pattern_sequence(self,
                             pattern_indices: Sequence[int],
                             exp_times: Optional[Union[Sequence[int], int]] = None,
                             dark_times: Union[Sequence[int], int] = 0,
                             triggered: bool = False,
                             clear_pattern_after_trigger: bool = True,
                             bit_depth: int = 1,
                             num_repeats: int = 0,
                             mode: str = 'pre-stored'):
        """
        Setup pattern sequence from patterns previously stored in DMD memory.
        """

        if isinstance(pattern_indices, int) or np.issubdtype(type(pattern_indices), np.integer):
            pattern_indices = [pattern_indices]
        elif isinstance(pattern_indices, np.ndarray):
            pattern_indices = pattern_indices.tolist()

        if exp_times is None:
            exp_times = self.min_time_us

        nimgs = len(pattern_indices)
        pic_indices, bit_indices = self._index_2pic_bit(pattern_indices)
        pic_indices = pic_indices.tolist()
        bit_indices = bit_indices.tolist()

        if mode == 'on-the-fly' and 0 not in bit_indices:
            raise ValueError("Known issue that if 0 is not included in the bit indices, then the patterns "
                             "displayed will not correspond with the indices supplied.")

        if isinstance(exp_times, int):
            exp_times = [exp_times]

        if not all(list(map(lambda t: isinstance(t, int), exp_times))):
            raise ValueError("exp_times must be a list of integers")

        if nimgs > 1 and len(exp_times) == 1:
            exp_times = exp_times * nimgs

        if isinstance(dark_times, int):
            dark_times = [dark_times]

        if not all(list(map(lambda t: isinstance(t, int), dark_times))):
            raise ValueError("dark_times must be a list of integers")

        if nimgs > 1 and len(dark_times) == 1:
            dark_times = dark_times * nimgs

        self.start_stop_sequence('stop')

        buffer = self.set_pattern_mode(mode)
        resp = self.decode_response(buffer)
        if resp['error']:
            print(self.read_error_description())

        self.start_stop_sequence('stop')

        for ii, (et, dt) in enumerate(zip(exp_times, dark_times)):
            buffer = self._pattern_display_lut_definition(ii,
                                                          exposure_time_us=et,
                                                          dark_time_us=dt,
                                                          wait_for_trigger=triggered,
                                                          clear_pattern_after_trigger=clear_pattern_after_trigger,
                                                          bit_depth=bit_depth,
                                                          stored_image_index=pic_indices[ii],
                                                          stored_image_bit_index=bit_indices[ii])
            resp = self.decode_response(buffer)
            if resp['error']:
                print(self.read_error_description())

        buffer = self._pattern_display_lut_configuration(nimgs, num_repeat=num_repeats)

        if buffer == []:
            print(self.read_error_description())
        else:
            resp = self.decode_response(buffer)
            if resp['error']:
                print(self.read_error_description())

        self.start_stop_sequence('start')

        if triggered:
            self.start_stop_sequence('stop')

    # =========================================================================
    # High-level preset/channel commands
    # =========================================================================
    def get_dmd_sequence(self,
                         modes: Sequence[str],
                         channels: Sequence[str],
                         nrepeats: Sequence[int] = 1,
                         noff_before: Sequence[int] = 0,
                         noff_after: Sequence[int] = 0,
                         blank: Sequence[bool] = False,
                         mode_pattern_indices: Sequence[Sequence[int]] = None):
        """
        Generate DMD patterns from a list of modes and channels.
        """
        if self.presets is None:
            raise ValueError("self.presets was None, but must be a dictionary populated with channels and modes.")

        if isinstance(channels, str):
            channels = [channels]
        if not isinstance(channels, list):
            raise ValueError(f"'channels' must be of type list, but was {type(channels)}")

        nmodes = len(channels)

        if isinstance(modes, str):
            modes = [modes]
        if not isinstance(modes, list):
            raise ValueError(f"'modes' must be of type list, but was {type(modes)}")
        if len(modes) == 1 and nmodes > 1:
            modes = modes * nmodes
        if len(modes) != nmodes:
            raise ValueError(f"len(modes)={len(modes):d} and nmodes={nmodes:d}, but these must be equal")

        if mode_pattern_indices is None:
            mode_pattern_indices = []
            for c, m in zip(channels, modes):
                npatterns = len(self.presets[c][m])
                mode_pattern_indices.append(np.arange(npatterns, dtype=int))

        if isinstance(mode_pattern_indices, int):
            mode_pattern_indices = [mode_pattern_indices]
        if not isinstance(mode_pattern_indices, list):
            raise ValueError(f"'mode_pattern_indices' must be of type list, but was {type(mode_pattern_indices)}")
        if len(mode_pattern_indices) == 1 and nmodes > 1:
            mode_pattern_indices = mode_pattern_indices * nmodes
        if len(mode_pattern_indices) != nmodes:
            raise ValueError(f"len(mode_pattern_indices)={len(mode_pattern_indices):d} and "
                             f"nmodes={nmodes:d}, but these must be equal")

        if isinstance(nrepeats, int):
            nrepeats = [nrepeats]
        if not isinstance(nrepeats, list):
            raise ValueError(f"'nrepeats' must be of type list, but was {type(nrepeats)}")
        if nrepeats is None:
            nrepeats = [1] * nmodes
        if len(nrepeats) == 1 and nmodes > 1:
            nrepeats = nrepeats * nmodes
        if len(nrepeats) != nmodes:
            raise ValueError(f"nrepeats={nrepeats:d} and nmodes={nmodes:d}, but these must be equal")

        if isinstance(noff_before, int):
            noff_before = [noff_before]
        if not isinstance(noff_before, list):
            raise ValueError(f"'noff_before' must be of type list, but was {type(noff_before)}")
        if len(noff_before) == 1 and nmodes > 1:
            noff_before = noff_before * nmodes
        if len(noff_before) != nmodes:
            raise ValueError(f"len(noff_before)={len(noff_before):d} and nmodes={nmodes:d}, but these must be equal")

        if isinstance(noff_after, int):
            noff_after = [noff_after]
        if not isinstance(noff_after, list):
            raise ValueError(f"'noff_after' must be of type list, but was {type(noff_after)}")
        if len(noff_after) == 1 and nmodes > 1:
            noff_after = noff_after * nmodes
        if len(noff_after) != nmodes:
            raise ValueError(f"len(noff_after)={len(noff_after):d} and nmodes={nmodes:d}, but these must be equal")

        if isinstance(blank, bool):
            blank = [blank]
        if not isinstance(blank, list):
            raise ValueError(f"'blank' must be of type list, but was {type(blank)}")
        if len(blank) == 1 and nmodes > 1:
            blank = blank * nmodes
        if len(blank) != nmodes:
            raise ValueError(f"len(blank)={len(blank):d} and nmodes={nmodes:d}, but these must be equal")

        f_inds = []
        for c, m, ind, nreps in zip(channels, modes, mode_pattern_indices, nrepeats):
            fi = np.array(np.atleast_1d(self.presets[c][m]), copy=True)
            fi = fi[ind]
            fi = np.hstack([fi] * nreps)
            f_inds.append(fi)

        for ii in range(nmodes):
            if noff_before[ii] != 0 or noff_after[ii] != 0:
                ioff_before = self.presets[channels[ii]]["off"] * np.ones(noff_before[ii], dtype=int)
                ioff_after = self.presets[channels[ii]]["off"] * np.ones(noff_after[ii], dtype=int)
                f_inds[ii] = np.concatenate((ioff_before, f_inds[ii], ioff_after), axis=0).astype(int)

        for ii in range(nmodes):
            if blank[ii]:
                npatterns = len(f_inds[ii])
                ioff = self.presets[channels[ii]]["off"]
                ioff_new = np.zeros((2 * npatterns), dtype=int)
                ioff_new[::2] = f_inds[ii]
                ioff_new[1::2] = ioff
                f_inds[ii] = ioff_new

        return np.hstack(f_inds)

    def program_dmd_seq(self,
                        modes: Sequence[str],
                        channels: Sequence[str],
                        nrepeats: Sequence[int] = 1,
                        noff_before: Sequence[int] = 0,
                        noff_after: Sequence[int] = 0,
                        blank: Sequence[bool] = False,
                        mode_pattern_indices: Sequence[Sequence[int]] = None,
                        triggered: bool = False,
                        exp_time_us: Optional[int] = None,
                        clear_pattern_after_trigger: bool = False,
                        verbose: bool = False) -> np.ndarray:
        """
        Convenience function for generating DMD pattern and programming DMD.
        """

        firmware_inds = self.get_dmd_sequence(modes, channels,
                                              nrepeats=nrepeats,
                                              noff_before=noff_before,
                                              noff_after=noff_after,
                                              blank=blank,
                                              mode_pattern_indices=mode_pattern_indices)

        self.debug = verbose
        self.start_stop_sequence('stop')

        delay1_us, mode_trig1 = self.get_trigger_in1()
        mode_trig2 = self.get_trigger_in2()

        self.set_pattern_sequence(firmware_inds,
                                  exp_time_us,
                                  triggered=triggered,
                                  clear_pattern_after_trigger=clear_pattern_after_trigger,
                                  mode='pre-stored')

        if verbose:
            print(f"{len(firmware_inds):d} firmware pattern indices: {firmware_inds}")
            print("finished programming DMD")

        return firmware_inds

    @staticmethod
    def _index_2pic_bit(firmware_indices) -> tuple:
        """Convert from single firmware pattern index to picture and bit indices."""
        pic_inds = np.asarray(firmware_indices) // 24
        bit_inds = firmware_indices - 24 * np.asarray(pic_inds)
        return pic_inds, bit_inds

    @staticmethod
    def _pic_bit2index(pic_inds, bit_inds) -> np.ndarray:
        """Convert from picture and bit indices to single firmware pattern index."""
        firmware_inds = np.asarray(pic_inds) * 24 + np.asarray(bit_inds)
        return firmware_inds


class dlp6500(dlpc900_dmd):
    width = 1920
    height = 1080
    pitch = 7.56
    dual_controller = False

    def __init__(self, *args, **kwargs):
        super(dlp6500, self).__init__(*args, **kwargs)


# Alias for backward compatibility
dlp6500win = dlp6500


class dlp9000(dlpc900_dmd):
    width = 2560
    height = 1600
    pitch = 7.56
    dual_controller = True

    def __init__(self, *args, **kwargs):
        super(dlp9000, self).__init__(*args, **kwargs)
