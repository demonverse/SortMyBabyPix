Python script stored on target device

Organise photos/videos by date order into folders that are created by year order 

Takes from one or two sources (I used USB devices/ssd cards via usb)

You need to create folders on target device (eg photos/videos)

To run:
python "D:\organize_photos.py"
python "D:\organize_videos.py"

(alter to your destination folder)

Might take a while depending on media processing volume

for verifying the backup in case of disk degradation/other 

python verify_backup.py "D:\Photos" --save manifest.txt

Copy manifest.txt alongside the backup. Then whenever you want to confirm the SD card hasn't degraded:

python verify_backup.py "E:\PhotosBackup" --check manifest.txt

