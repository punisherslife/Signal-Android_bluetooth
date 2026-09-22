#pragma once
#include <functional>
#include <memory>
namespace webrtc {
class AudioFrame;
// Test double for the public interface checked against WebRTC 7871f.
class AudioFrameProcessor {
 public:
  using OnAudioFrameCallback = std::function<void(std::unique_ptr<AudioFrame>)>;
  virtual ~AudioFrameProcessor() = default;
  virtual void Process(std::unique_ptr<AudioFrame>) = 0;
  virtual void SetSink(OnAudioFrameCallback) = 0;
};
}
