// SPDX-License-Identifier: AGPL-3.0-only
// Tests the shipped processor header with explicit WebRTC/RNNoise doubles.
#include <cassert>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdlib>
#include <iostream>
#include <limits>
#include <thread>
#include "rnnoise_audio_frame_processor.h"

struct DenoiseState { int count; };
std::atomic<int> allocations{0};
std::atomic<bool> fail_alloc{false};
extern "C" void* __real_malloc(size_t);
extern "C" void* __wrap_malloc(size_t size) {
  ++allocations;
  if (fail_alloc) return nullptr;
  return __real_malloc(size);
}
int initialized = 0;
int processed = 0;
bool fail_init = false;
int output_mode = 0;
extern "C" int rnnoise_get_size() { return sizeof(DenoiseState); }
extern "C" int rnnoise_get_frame_size() { return 480; }
extern "C" int rnnoise_init(DenoiseState* s, RNNModel*) {
  assert(s); ++initialized; s->count = 0; return fail_init ? -1 : 0;
}
extern "C" float rnnoise_process_frame(DenoiseState* s, float* out, const float* in) {
  ++processed; ++s->count;
  for (int i = 0; i < 480; ++i) out[i] = in[i] + 1;
  if (output_mode == 1) { out[0] = 40000; out[1] = -40000; out[2] = .5f; out[3] = -.5f; }
  if (output_mode == 2) out[479] = std::numeric_limits<float>::quiet_NaN();
  if (output_mode == 3) out[479] = std::numeric_limits<float>::infinity();
  return 0;
}
using webrtc::AudioFrame;
using webrtc::jni::RnnoiseAudioFrameProcessor;
using webrtc::jni::SetRnnoiseEnabled;
std::unique_ptr<AudioFrame> frame() {
  auto f = std::make_unique<AudioFrame>();
  auto* data = f->mutable_data();
  for (int i = 0; i < 480; ++i) data[i] = 100;
  return f;
}
int main() {
  SetRnnoiseEnabled(false);
  RnnoiseAudioFrameProcessor p;
  assert(initialized == 0);
  std::unique_ptr<AudioFrame> result;
  p.SetSink([&](std::unique_ptr<AudioFrame> f) { result = std::move(f); });
  auto f = frame(); auto* identity = f.get(); const int before = allocations;
  p.Process(std::move(f));
  assert(result.get() == identity && result->data()[0] == 100 && result->timestamp_ == 777);
  assert(initialized == 0 && processed == 0 && allocations == before);
  SetRnnoiseEnabled(true);
  f = frame(); const int active_allocs = allocations;
  p.Process(std::move(f));
  assert(initialized == 1 && processed == 1 && result->data()[0] == 101 && allocations == active_allocs);
  p.Process(frame()); assert(initialized == 1);
  SetRnnoiseEnabled(true); p.Process(frame()); assert(initialized == 1);
  SetRnnoiseEnabled(false); SetRnnoiseEnabled(true); p.Process(frame()); assert(initialized == 2);
  f = frame(); f->Mute(); const int prev = processed; p.Process(std::move(f));
  assert(result->muted() && processed == prev);
  p.Process(frame()); assert(initialized == 3);
  for (int which = 0; which < 3; ++which) {
    f = frame();
    if (which == 0) f->sample_rate_hz_ = 16000;
    if (which == 1) f->num_channels_ = 2;
    if (which == 2) f->samples_per_channel_ = 160;
    const int prev = processed; p.Process(std::move(f));
    assert(processed == prev && result->data()[0] == 100);
    p.Process(frame()); assert(initialized == 4 + which);
  }
  output_mode = 1; p.Process(frame());
  assert(result->data()[0] == 32767 && result->data()[1] == -32768);
  assert(result->data()[2] == 1 && result->data()[3] == -1);
  for (int bad : {2, 3}) {
    RnnoiseAudioFrameProcessor q;
    q.SetSink([&](std::unique_ptr<AudioFrame> f) { result = std::move(f); });
    output_mode = bad; q.Process(frame());
    assert(result->data()[0] == 100 && result->data()[479] == 100);
    const int prev = processed; output_mode = 0; q.Process(frame()); assert(processed == prev);
  }
  {
    RnnoiseAudioFrameProcessor q; fail_init = true;
    q.SetSink([&](std::unique_ptr<AudioFrame> f) { result = std::move(f); });
    q.Process(frame()); assert(result->data()[0] == 100);
    const int init = initialized; q.Process(frame()); assert(initialized == init);
    fail_init = false;
  }
  {
    fail_alloc = true; RnnoiseAudioFrameProcessor q; fail_alloc = false;
    q.SetSink([&](std::unique_ptr<AudioFrame> f) { result = std::move(f); });
    const int prev = processed; q.Process(frame());
    assert(result->data()[0] == 100 && processed == prev);
  }
  // Concurrent Process calls and toggles must not race the model or sink.
  std::atomic<int> delivered{0};
  p.SetSink([&](std::unique_ptr<AudioFrame> f) { assert(f); ++delivered; });
  std::thread toggle([] { for (int i = 0; i < 2000; ++i) SetRnnoiseEnabled(i & 1); });
  std::thread a([&] { for (int i = 0; i < 1000; ++i) p.Process(frame()); });
  std::thread b([&] { for (int i = 0; i < 1000; ++i) p.Process(frame()); });
  a.join(); b.join(); toggle.join(); assert(delivered == 2000);
  p.SetSink(nullptr); p.Process(frame()); p.Process(nullptr); assert(delivered == 2000);

  // SetSink(nullptr) must wait for an in-flight callback, then quiesce it.
  std::mutex gate; std::condition_variable cv;
  bool entered = false, release = false; std::atomic<bool> removed{false};
  p.SetSink([&](std::unique_ptr<AudioFrame>) {
    std::unique_lock<std::mutex> lock(gate); entered = true; cv.notify_all();
    cv.wait(lock, [&] { return release; });
  });
  std::thread sending([&] { p.Process(frame()); });
  { std::unique_lock<std::mutex> lock(gate); cv.wait(lock, [&] { return entered; }); }
  std::thread removing([&] { p.SetSink(nullptr); removed = true; });
  assert(!removed);
  { std::lock_guard<std::mutex> lock(gate); release = true; cv.notify_all(); }
  sending.join(); removing.join(); assert(removed);
  std::cout << "PASS: bypass, transitions, reset, mute, formats, saturation, NaN/Inf, failures, malloc count, concurrent delivery, sink shutdown\n";
}
