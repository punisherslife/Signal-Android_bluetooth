#pragma once
extern "C" {
struct DenoiseState;
struct RNNModel;
int rnnoise_get_size();
int rnnoise_get_frame_size();
int rnnoise_init(DenoiseState*, RNNModel*);
float rnnoise_process_frame(DenoiseState*, float*, const float*);
}
