#pragma once
#include <array>
#include <cstdint>
#include <cstddef>
namespace webrtc {
// Only the interface used by our processor; not a WebRTC implementation test.
class AudioFrame {
 public:
  int sample_rate_hz_ = 48000;
  size_t num_channels_ = 1;
  size_t samples_per_channel_ = 480;
  uint32_t timestamp_ = 777;
  bool muted() const { return muted_; }
  void Mute() { muted_ = true; }
  const int16_t* data() const { return data_.data(); }
  int16_t* mutable_data() {
    if (muted_) { data_.fill(0); muted_ = false; }
    return data_.data();
  }
 private:
  bool muted_ = true;
  std::array<int16_t, 960> data_{};
};
}
