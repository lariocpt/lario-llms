#!/bin/bash
# Run this script to package the windows-setup folder into a zip file for Daniel.

echo "Packaging Windows Setup Files..."

# Go to the parent directory to zip the folder cleanly
cd /mnt/Shared/personal/lario-llms

# Remove old archive if it exists
rm -f windows-setup-archive.zip

# Create the zip archive
zip -r windows-setup-archive.zip windows-setup -x "windows-setup/package-windows-setup.sh"

echo "Done! The archive is located at: /mnt/Shared/personal/lario-llms/windows-setup-archive.zip"
echo "You can send this zip file directly to Daniel."
