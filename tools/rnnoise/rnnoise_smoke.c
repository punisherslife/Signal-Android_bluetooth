/* SPDX-License-Identifier: AGPL-3.0-only */
/* Host smoke/CPU diagnostic for the actual pinned model, not an Android benchmark. */
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include "rnnoise.h"
int main(void) {
  const int size = rnnoise_get_size();
  if (size <= 0 || rnnoise_get_frame_size() != 480) return 1;
  DenoiseState* state = (DenoiseState*)malloc((size_t)size);
  if (!state || rnnoise_init(state, NULL)) { free(state); return 2; }
  float samples[480];
  uint32_t random = 1;
  double checksum = 0;
  const clock_t start = clock();
  for (int frame = 0; frame < 300; ++frame) {
    for (int i = 0; i < 480; ++i) {
      random = random * 1664525u + 1013904223u;
      samples[i] = 8000.f * sinf((float)(frame * 480 + i) * .04f) + (float)(random >> 20) - 2048.f;
    }
    rnnoise_process_frame(state, samples, samples);
    for (int i = 0; i < 480; ++i) {
      if (!isfinite(samples[i])) { free(state); return 3; }
      checksum += fabsf(samples[i]);
    }
    if (frame == 149 && rnnoise_init(state, NULL)) { free(state); return 4; }
  }
  const double seconds = (double)(clock() - start) / CLOCKS_PER_SEC;
  printf("RNNoise actual model: state=%d bytes, mean_cpu=%.3f ms/frame, checksum=%.0f\n", size, seconds * 1000 / 300, checksum);
  free(state);
  return checksum > 0 ? 0 : 5;
}
