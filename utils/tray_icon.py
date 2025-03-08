import pystray
from PIL import Image
import os
import signal
import webbrowser

def create_tray_icon():
    """Creates system tray icon with menu items.
    
    Returns:
        pystray.Icon: Configured tray icon instance
        
    Menu Items:
        - Open Interface: Launches web interface
        - Exit: Terminates application
    """

    global tray_icon
    base_dir = os.path.dirname(os.path.abspath(__file__))
    icon_path = os.path.abspath(os.path.join(base_dir, '../static/favicon.ico'))  # 使用绝对路径
    image = Image.open(icon_path)
    menu = pystray.Menu(
        pystray.MenuItem('打开界面', lambda: webbrowser.open('http://localhost:8000')),
        pystray.MenuItem('退出程序', terminate_app)
    )
    tray_icon = pystray.Icon("name", image, "DeepQuery", menu)
    tray_icon.run()
    return tray_icon

def terminate_app():
    global tray_icon
    # 终止程序
    os.kill(os.getpid(), signal.CTRL_C_EVENT)
    if tray_icon:
        tray_icon.stop()

def run_tray_icon():
    global tray_icon
    tray_icon = create_tray_icon()
    tray_icon.run()
