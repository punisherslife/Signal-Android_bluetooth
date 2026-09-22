/* SPDX-License-Identifier: AGPL-3.0-only */
#ifndef SDK_ANDROID_SRC_JNI_PC_RNNOISE_AUDIO_FRAME_PROCESSOR_H_
#define SDK_ANDROID_SRC_JNI_PC_RNNOISE_AUDIO_FRAME_PROCESSOR_H_

#include <array>
#include <atomic>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <memory>
#include <mutex>
#include <utility>

#include "api/audio/audio_frame.h"
#include "api/audio/audio_frame_processor.h"
#include "third_party/rnnoise_little/include/rnnoise.h"

namespace webrtc {
namespace jni {

// One coherent snapshot: bit 0 is enabled; the remaining bits change on every
// transition. A rapid OFF/ON between frames must still clear the old history.
inline std::atomic<uint32_t> g_rnnoise_control{0};
static_assert(std::atomic<uint32_t>::is_always_lock_free);

inline void SetRnnoiseEnabled(bool enabled) {
  uint32_t previous = g_rnnoise_control.load(std::memory_order_relaxed);
  while ((previous & 1u) != static_cast<uint32_t>(enabled)) {
    const uint32_t next = ((previous + 2u) & ~1u) | static_cast<uint32_t>(enabled);
    if (g_rnnoise_control.compare_exchange_weak(
            previous, next, std::memory_order_relaxed)) {
      break;
    }
  }
}

class RnnoiseAudioFrameProcessor final : public AudioFrameProcessor {
 public:
  RnnoiseAudioFrameProcessor() {
    // The pinned rnnoise_create() dereferences malloc's result before checking
    // it. Allocate here, check it, and defer model initialization until ON.
    const int size = rnnoise_get_size();
    if (size > 0 && rnnoise_get_frame_size() == kFrameSize) {
      state_ = static_cast<DenoiseState*>(std::malloc(static_cast<size_t>(size)));
    }
  }

  ~RnnoiseAudioFrameProcessor() override { std::free(state_); }

  void Process(std::unique_ptr<AudioFrame> frame) override {
    if (!frame) return;
    // The pinned WebRTC queue serializes Process, but the public interface also
    // requires thread-safe SetSink. Keep one lock and hold it through delivery:
    // SetSink(nullptr) must not return while the old callback can still run.
    // WebRTC's sink only posts a task; it does not call back into this object.
    std::lock_guard<std::mutex> lock(mutex_);
    if (!sink_callback_) return;

    const uint32_t control = g_rnnoise_control.load(std::memory_order_relaxed);
    if ((control & 1u) == 0 || frame->muted() ||
        frame->sample_rate_hz_ != 48000 || frame->num_channels_ != 1 ||
        frame->samples_per_channel_ != kFrameSize) {
      reset_pending_ = true;
    } else if (state_ && !failed_) {
      ProcessEnabledFrame(*frame, control);
    }
    sink_callback_(std::move(frame));
  }

  void SetSink(OnAudioFrameCallback sink_callback) override {
    std::lock_guard<std::mutex> lock(mutex_);
    sink_callback_ = std::move(sink_callback);
    reset_pending_ = true;
  }

 private:
  static constexpr int kFrameSize = 480;

  static int16_t FloatToInt16(float value) {
    if (value >= 32767.0f) return 32767;
    if (value <= -32768.0f) return -32768;
    return static_cast<int16_t>(value >= 0.0f ? value + 0.5f : value - 0.5f);
  }

  void ProcessEnabledFrame(AudioFrame& frame, uint32_t control) {
    if (reset_pending_ || control != last_control_) {
      if (rnnoise_init(state_, nullptr) != 0) {
        // Preserve call audio and avoid retrying a broken model every 10 ms.
        failed_ = true;
        return;
      }
      reset_pending_ = false;
      last_control_ = control;
    }
    const int16_t* input = frame.data();
    for (int i = 0; i < kFrameSize; ++i) scratch_[i] = input[i];
    rnnoise_process_frame(state_, scratch_.data(), scratch_.data());
    // Validate before modifying the frame. NaN-to-integer conversion is UB;
    // a bad DSP result must leave the original frame intact.
    for (float sample : scratch_) {
      if (!std::isfinite(sample)) {
        failed_ = true;
        return;
      }
    }
    int16_t* output = frame.mutable_data();
    for (int i = 0; i < kFrameSize; ++i) output[i] = FloatToInt16(scratch_[i]);
  }

  DenoiseState* state_ = nullptr;
  uint32_t last_control_ = 0;
  bool reset_pending_ = true;
  bool failed_ = false;
  std::array<float, kFrameSize> scratch_{};
  std::mutex mutex_;
  OnAudioFrameCallback sink_callback_;
};

}  // namespace jni
}  // namespace webrtc
#endif
