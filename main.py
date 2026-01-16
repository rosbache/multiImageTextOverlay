"""
Image Metadata Overlay - Main Entry Point

Processes all JPG images in the input/ folder and creates copies
with metadata overlays in the output/ folder.
"""

import os
from pathlib import Path
from image_processor import process_image


def main():
    """
    Main function to process all images in input directory.
    """
    # Define directories
    input_dir = Path("input")
    output_dir = Path("output")
    
    # Create output directory if it doesn't exist
    output_dir.mkdir(exist_ok=True)
    
    # Check if input directory exists
    if not input_dir.exists():
        print(f"Error: Input directory '{input_dir}' does not exist.")
        print("Please create the 'input' folder and add JPG images to process.")
        return
    
    # Get all JPG files from input directory
    jpg_files = list(input_dir.glob("*.jpg")) + list(input_dir.glob("*.JPG")) + \
                list(input_dir.glob("*.jpeg")) + list(input_dir.glob("*.JPEG"))
    
    if not jpg_files:
        print(f"No JPG images found in '{input_dir}' directory.")
        print("Please add JPG images to the 'input' folder.")
        return
    
    print(f"Found {len(jpg_files)} image(s) to process.\n")
    
    # Process each image
    success_count = 0
    for jpg_file in jpg_files:
        print(f"Processing: {jpg_file.name}...", end=" ")
        
        # Create output path with same filename
        output_path = output_dir / jpg_file.name
        
        # Process the image
        if process_image(str(jpg_file), str(output_path)):
            print("✓ Done")
            success_count += 1
        else:
            print("✗ Failed")
    
    # Summary
    print(f"\n{'='*50}")
    print(f"Processing complete!")
    print(f"Successfully processed: {success_count}/{len(jpg_files)} images")
    print(f"Output saved to: {output_dir.absolute()}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
