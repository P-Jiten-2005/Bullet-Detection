import cv2
import numpy as np
import os

def draw_target():
    # Create a 1000x1000 white canvas
    img = np.ones((1000, 1000, 3), dtype=np.uint8) * 255
    cx, cy = 500, 500

    # Draw high-contrast corner registration marks (Anchor features for ORB matching)
    # This simulates ArUco-like corner features or target board borders
    cv2.rectangle(img, (20, 20), (100, 100), (0, 0, 0), -1)
    cv2.rectangle(img, (900, 20), (980, 100), (0, 0, 0), -1)
    cv2.rectangle(img, (20, 900), (100, 980), (0, 0, 0), -1)
    cv2.rectangle(img, (900, 900), (980, 980), (0, 0, 0), -1)
    
    # Draw crosshair helper lines
    cv2.line(img, (150, 500), (850, 500), (0, 0, 0), 1)
    cv2.line(img, (500, 150), (500, 850), (0, 0, 0), 1)

    # Concentric rings (10 down to 1)
    # Radii from 400 pixels spacing down by 40 pixels
    for i in range(1, 11):
        radius = (11 - i) * 40
        # Draw ring boundaries
        cv2.circle(img, (cx, cy), radius, (0, 0, 0), 2)
        # Add ring number annotations
        if radius > 40:
            cv2.putText(img, str(i), (cx - 5, cy - radius + 25), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
            cv2.putText(img, str(i), (cx - 5, cy + radius - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)

    # Bullseye center
    cv2.circle(img, (cx, cy), 15, (0, 0, 255), -1) # Red bullseye center
    return img

def main():
    print("Generating target baseline target image...")
    target = draw_target()
    
    # Save baseline image
    baseline_filename = "test_baseline.jpg"
    cv2.imwrite(baseline_filename, target)
    print(f"Saved: {baseline_filename}")

    # Generate capture image by adding 3 marker dot "bullet holes"
    print("Generating capture target frame with simulated camera jitter and bullet impacts...")
    capture = target.copy()
    
    # Simulated bullet holes (black marker dots)
    # Hole 1: Near bullseye (9 ring)
    cv2.circle(capture, (470, 480), 8, (10, 10, 10), -1)
    # Hole 2: In 7 ring
    cv2.circle(capture, (530, 620), 9, (15, 15, 15), -1)
    # Hole 3: In 5 ring
    cv2.circle(capture, (660, 400), 7, (5, 5, 5), -1)

    # Introduce synthetic camera tripod shift & rotation
    # Shift 6px X, 4px Y, and rotate by 0.8 degrees
    rows, cols, _ = capture.shape
    angle = 0.8
    scale = 1.0
    M = cv2.getRotationMatrix2D((cols/2, rows/2), angle, scale)
    # Apply translation shift in transformation matrix
    M[0, 2] += 6.0
    M[1, 2] += 4.0
    
    # Warp target image to simulate real camera feedback
    jitter_capture = cv2.warpAffine(capture, M, (cols, rows), borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255))
    
    capture_filename = "test_capture.jpg"
    cv2.imwrite(capture_filename, jitter_capture)
    print(f"Saved: {capture_filename}")
    print("Generation complete! Use these two images inside the CXR-AIM dashboard.")

if __name__ == "__main__":
    main()
