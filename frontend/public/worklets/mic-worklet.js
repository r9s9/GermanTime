// Downsamples the browser's native mic sample rate to 16 kHz mono PCM16 and
// emits 20 ms (320-sample) frames to the main thread. Runs on the audio
// rendering thread — plain JS, no bundler, loaded via audioWorklet.addModule.

class MicWorklet extends AudioWorkletProcessor {
  constructor() {
    super();
    const targetRate = 16000;
    this.ratio = sampleRate / targetRate; // `sampleRate` is an AudioWorkletGlobalScope global
    this.frameSamples = 320; // 20ms @ 16kHz
    this.outBuffer = new Int16Array(this.frameSamples);
    this.outIndex = 0;
    this.resampleAcc = 0;
  }

  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (!channel) return true;

    for (let i = 0; i < channel.length; i++) {
      this.resampleAcc += 1;
      if (this.resampleAcc >= this.ratio) {
        this.resampleAcc -= this.ratio;
        const s = Math.max(-1, Math.min(1, channel[i]));
        this.outBuffer[this.outIndex++] = s < 0 ? s * 0x8000 : s * 0x7fff;
        if (this.outIndex >= this.frameSamples) {
          const copy = this.outBuffer.slice();
          this.port.postMessage(copy.buffer, [copy.buffer]);
          this.outIndex = 0;
        }
      }
    }
    return true;
  }
}

registerProcessor("mic-worklet", MicWorklet);
