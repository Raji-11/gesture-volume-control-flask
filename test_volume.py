from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
from ctypes import cast, POINTER
from comtypes import CLSCTX_ALL

devices = AudioUtilities.GetSpeakers()
interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
volume = cast(interface, POINTER(IAudioEndpointVolume))

# Print current system volume
print("Current Volume:", volume.GetMasterVolumeLevelScalar())

# Set system volume to 30%
volume.SetMasterVolumeLevelScalar(0.3, None)
print("Volume set to 30%")

# Set system volume to 90%
volume.SetMasterVolumeLevelScalar(0.9, None)
print("Volume set to 90%")
