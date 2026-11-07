GeotaxPro
Open-source software for automated video tracking and quantification of the Drosophila RING assay.
GeotaxPro is a standalone desktop application developed to eliminate inter-observer variability and manual frame-by-frame counting in the Rapid Iterative Negative Geotaxis (RING) assay for Drosophila melanogaster.

Key Features
Computer Vision Pipeline: Built in Python using OpenCV with a Mixture of Gaussians (MOG2) background subtraction algorithm.
Two-Stage Filtering: Minimum-area filter to remove camera noise and aspect-ratio filter for reliable target segmentation.
Metric Calibration: Intuitive manual calibration to convert pixel coordinates into physical units (centimeters).
Automated Quantification: Computes fly ascension heights, climbing velocities, time to target threshold, and cumulative arrivals over time.
User-Friendly GUI: Lightweight desktop interface (no external Python dependencies required).
Quick Start
Run Instalador_GeotaxPro.exe and open the application.
Load the assay video (.mp4).
Enter the vial length and target finish line height in centimeters.
Calibrate by clicking the base and cap of the reference tube.
Press Start to analyze the video and export metrics.

Valencia-Vital, N. V., & Santos-Cruz, L. F. (2026). An affordable, open-source semi-automated device for the Drosophila RING assay. Drosophila Information Service.
