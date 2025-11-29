# Use the official Playwright image
FROM mcr.microsoft.com/playwright/python:v1.37.0-jammy

# Switch to root temporarily to install dependencies and setup permissions
USER root

# Set the working directory
WORKDIR /app

# Copy the requirements file specifically
COPY requirements.txt /app/

# Install Python dependencies globally (as root)
# This ensures they are available to all users
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application files
COPY . /app

# The existing user with UID 1000 needs ownership of the app directory
# We use the ID 1000 directly to avoid guessing the username (e.g., pwuser vs ubuntu)
RUN chown -R 1000:1000 /app

# Switch to the existing user with UID 1000 for security and HF Spaces compatibility
USER 1000

# Set HOME to the app directory so that Playwright/cache writes go here
ENV HOME=/app

# Install Chromium specifically for the user (since we changed HOME)
# This ensures the browser binaries are accessible to the non-root user
RUN playwright install chromium

# Expose the port
EXPOSE 7860

# Start the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]