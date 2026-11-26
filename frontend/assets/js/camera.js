// Webcam helper shared by Live recognition and People → capture. Handles device listing,
// start/stop, and grabbing a JPEG frame at the camera's native resolution.

export class Camera {
  constructor(video) { this.video = video; this.stream = null; }

  get active() { return !!this.stream; }

  static async devices() {
    if (!navigator.mediaDevices?.enumerateDevices) return [];
    return (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === 'videoinput');
  }

  async start(deviceId) {
    this.stop();
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error('Camera access needs HTTPS or http://localhost. Open the console on this machine or enable TLS.');
    }
    const video = deviceId ? { deviceId: { exact: deviceId } } : { facingMode: 'user' };
    Object.assign(video, { width: { ideal: 1280 }, height: { ideal: 720 } });
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ video, audio: false });
    } catch (e) {
      const msg = { NotAllowedError: 'Camera access is blocked for this site. Click the camera/lock icon at the left of the address bar, set Camera to “Allow”, then press Try again.',
        NotFoundError: 'No camera found on this device.', NotReadableError: 'The camera could not be opened: another app (Zoom, Teams, another tab) is using it, or the camera driver/USB connection failed. Close other camera apps; if it persists see README → Troubleshooting → Camera.' }[e.name];
      throw new Error(msg || e.message);
    }
    this.video.srcObject = this.stream;
    await this.video.play();
    return this.stream.getVideoTracks()[0]?.getSettings?.().deviceId;
  }

  stop() {
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    if (this.video) this.video.srcObject = null;
  }

  /** Returns {blob, width, height}. Downscales so the longer side ≤ maxSide (saves bandwidth, SCRFD runs at 640 anyway). */
  async grab(maxSide = 960, quality = 0.85) {
    const v = this.video;
    if (!v.videoWidth) return null;
    const s = Math.min(1, maxSide / Math.max(v.videoWidth, v.videoHeight));
    const w = Math.round(v.videoWidth * s), h = Math.round(v.videoHeight * s);
    const c = this._canvas || (this._canvas = document.createElement('canvas'));
    c.width = w; c.height = h;
    c.getContext('2d').drawImage(v, 0, 0, w, h);
    const blob = await new Promise((r) => c.toBlob(r, 'image/jpeg', quality));
    return { blob, width: w, height: h };
  }
}
