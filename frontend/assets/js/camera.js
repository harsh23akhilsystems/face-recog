// Webcam helper shared by Live recognition and People → capture. Handles device listing,
// start/stop, and grabbing a JPEG frame at the camera's native resolution.

// The chosen camera is remembered per browser so every page (Live, People → Webcam) opens the same device.
// Without this, pages that offer no picker fall back to the OS default, which on laptops with a phone/virtual
// camera is usually the built-in one.
const STORE_KEY = 'fg-camera';
const loadPreferred = () => { try { return localStorage.getItem(STORE_KEY) || undefined; } catch { return undefined; } };
const savePreferred = (id) => { try { if (id) localStorage.setItem(STORE_KEY, id); } catch { /* private mode */ } };

export class Camera {
  constructor(video) { this.video = video; this.stream = null; }

  get active() { return !!this.stream; }

  static async devices() {
    if (!navigator.mediaDevices?.enumerateDevices) return [];
    return (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === 'videoinput');
  }

  static get preferred() { return loadPreferred(); }

  /** Start `deviceId`, or the last camera used on any page, or the OS default. */
  async start(deviceId) {
    this.stop();
    const remembered = !deviceId && loadPreferred();
    if (remembered) {
      try { return await this._open(remembered); } catch { /* unplugged or renamed: fall through to default */ }
    }
    return this._open(deviceId);
  }

  async _open(deviceId) {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error('Camera access needs HTTPS or http://localhost. Open the console on this machine or enable TLS.');
    }
    const video = deviceId ? { deviceId: { exact: deviceId } } : { facingMode: 'user' };
    // 30 fps caps the exposure at ~33 ms on most webcams, which keeps motion blur down (enrollment photos).
    Object.assign(video, { width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 30 } });
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ video, audio: false });
    } catch (e) {
      const msg = { NotAllowedError: 'Camera access is blocked for this site. Click the camera/lock icon at the left of the address bar, set Camera to “Allow”, then press Try again.',
        NotFoundError: 'No camera found on this device.', NotReadableError: 'The camera could not be opened: another app (Zoom, Teams, another tab) is using it, or the camera driver/USB connection failed. Close other camera apps; if it persists see README → Troubleshooting → Camera.' }[e.name];
      throw new Error(msg || e.message);
    }
    this.video.srcObject = this.stream;
    await this.video.play();
    const id = this.stream.getVideoTracks()[0]?.getSettings?.().deviceId;
    savePreferred(id);
    return id;
  }

  stop() {
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    if (this.video) this.video.srcObject = null;
  }

  /** Canvas holding the most recent `grab()` frame (valid until the next grab). */
  get frame() { return this._canvas || null; }

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
