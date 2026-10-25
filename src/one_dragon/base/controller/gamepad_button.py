"""手柄按键的显示名称与配置值，不加载设备或系统输入模块。"""

from enum import Enum

from one_dragon.base.config.config_item import ConfigItem


class XboxButtonEnum(Enum):

    A = ConfigItem('A', 'xbox_a')
    B = ConfigItem('B', 'xbox_b')
    X = ConfigItem('X', 'xbox_x')
    Y = ConfigItem('Y', 'xbox_y')
    LT = ConfigItem('LT', 'xbox_lt')
    RT = ConfigItem('RT', 'xbox_rt')
    LB = ConfigItem('LB', 'xbox_lb')
    RB = ConfigItem('RB', 'xbox_rb')
    L_STICK_W = ConfigItem('左摇杆-上', 'xbox_ls_up')
    L_STICK_S = ConfigItem('左摇杆-下', 'xbox_ls_down')
    L_STICK_A = ConfigItem('左摇杆-左', 'xbox_ls_left')
    L_STICK_D = ConfigItem('左摇杆-右', 'xbox_ls_right')
    L_THUMB = ConfigItem('左摇杆-按下', 'xbox_l_thumb')
    R_THUMB = ConfigItem('右摇杆-按下', 'xbox_r_thumb')
    DPAD_UP = ConfigItem('十字键-上', 'xbox_dpad_up')
    DPAD_DOWN = ConfigItem('十字键-下', 'xbox_dpad_down')
    DPAD_LEFT = ConfigItem('十字键-左', 'xbox_dpad_left')
    DPAD_RIGHT = ConfigItem('十字键-右', 'xbox_dpad_right')
    START = ConfigItem('START', 'xbox_start')
    BACK = ConfigItem('BACK', 'xbox_back')
    R_STICK_W = ConfigItem('右摇杆-上', 'xbox_rs_up')
    R_STICK_S = ConfigItem('右摇杆-下', 'xbox_rs_down')
    R_STICK_A = ConfigItem('右摇杆-左', 'xbox_rs_left')
    R_STICK_D = ConfigItem('右摇杆-右', 'xbox_rs_right')
    GUIDE = ConfigItem('GUIDE', 'xbox_guide')


class Ds4ButtonEnum(Enum):

    CROSS = ConfigItem('✕', 'ds4_cross')
    CIRCLE = ConfigItem('○', 'ds4_circle')
    SQUARE = ConfigItem('□', 'ds4_square')
    TRIANGLE = ConfigItem('△', 'ds4_triangle')
    L2 = ConfigItem('L2', 'ds4_l2')
    R2 = ConfigItem('R2', 'ds4_r2')
    L1 = ConfigItem('L1', 'ds4_l1')
    R1 = ConfigItem('R1', 'ds4_r1')
    L_STICK_W = ConfigItem('左摇杆-上', 'ds4_ls_up')
    L_STICK_S = ConfigItem('左摇杆-下', 'ds4_ls_down')
    L_STICK_A = ConfigItem('左摇杆-左', 'ds4_ls_left')
    L_STICK_D = ConfigItem('左摇杆-右', 'ds4_ls_right')
    L_THUMB = ConfigItem('左摇杆-按下', 'ds4_l_thumb')
    R_THUMB = ConfigItem('右摇杆-按下', 'ds4_r_thumb')
    DPAD_UP = ConfigItem('十字键-上', 'ds4_dpad_up')
    DPAD_DOWN = ConfigItem('十字键-下', 'ds4_dpad_down')
    DPAD_LEFT = ConfigItem('十字键-左', 'ds4_dpad_left')
    DPAD_RIGHT = ConfigItem('十字键-右', 'ds4_dpad_right')
    OPTIONS = ConfigItem('OPTIONS', 'ds4_options')
    SHARE = ConfigItem('SHARE', 'ds4_share')
    TOUCHPAD = ConfigItem('触控板', 'ds4_touchpad')
    R_STICK_W = ConfigItem('右摇杆-上', 'ds4_rs_up')
    R_STICK_S = ConfigItem('右摇杆-下', 'ds4_rs_down')
    R_STICK_A = ConfigItem('右摇杆-左', 'ds4_rs_left')
    R_STICK_D = ConfigItem('右摇杆-右', 'ds4_rs_right')
    PS = ConfigItem('PS', 'ds4_ps')
