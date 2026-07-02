/** Opens the mic with echo cancellation (needed for barge-in over speakers)
 * and streams 20 ms PCM16 frames via onFrame until stop() is called.
 */
export async function startMicCapture(
  ctx: AudioContext,
  onFrame: (frame: ArrayBuffer) => void,
): Promise<{ stop: () => void }> {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
  });

  await ctx.audioWorklet.addModule("/worklets/mic-worklet.js");
  const source = ctx.createMediaStreamSource(stream);
  const node = new AudioWorkletNode(ctx, "mic-worklet");
  node.port.onmessage = (ev: MessageEvent<ArrayBuffer>) => onFrame(ev.data);
  source.connect(node);
  // AudioWorkletNode needs a destination-graph connection to keep running in
  // some browsers even though we discard its (silent) output.
  const sink = ctx.createGain();
  sink.gain.value = 0;
  node.connect(sink);
  sink.connect(ctx.destination);

  return {
    stop: () => {
      node.port.onmessage = null;
      node.disconnect();
      source.disconnect();
      sink.disconnect();
      for (const track of stream.getTracks()) track.stop();
    },
  };
}
