// Validate the served kernel against an independent E4M3 enumeration oracle.
// Reference semantics: DeepSeek-V4.1-Flash-1017 inference/kernel.py act_quant,
// commit 1bae0e1088993b9b82de08f59de5be5a34e42170 (MIT).
// nvcc -O2 -std=c++17 -arch=sm_121 --fmad=false --ftz=false \
//   tools/qualification/check_1017_fp8.cu -o /tmp/check-1017-fp8
#include "../../zig/kernels/cuda/dsv41_ops.cu"
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>
#define CHECK(expr) do { cudaError_t e=(expr); if(e!=cudaSuccess) { fprintf(stderr,"%s: %s\n",#expr,cudaGetErrorString(e)); exit(2); } } while(0)
static float f32(uint16_t b) { uint32_t u=uint32_t(b)<<16;float f;memcpy(&f,&u,4);return f; }
static uint16_t bf16(float f) { uint32_t u;memcpy(&u,&f,4);return uint16_t((u+0x7fff+((u>>16)&1))>>16); }
static float fp8_value(unsigned b) {
    unsigned e=b>>3,m=b&7;
    return e ? std::ldexp(1.0f+float(m)/8,int(e)-7) : std::ldexp(float(m),-9);
}
static float nearest_fp8(float f) {
    const float v=std::min(448.0f,std::fabs(f));
    unsigned best=0;float delta=v;
    for(unsigned b=1;b<=126;++b) {
        float d=std::fabs(v-fp8_value(b));
        if(d<delta || (d==delta && (b&1)==0)) {best=b;delta=d;}
    }
    return std::copysign(fp8_value(best),f);
}
static void oracle(const std::vector<uint16_t>& input,std::vector<uint16_t>& output) {
    for(size_t i=0;i<input.size();i+=32) {
        float maximum=1e-4f;
        for(size_t j=0;j<32;++j) maximum=std::max(maximum,std::fabs(f32(input[i+j])));
        // Force the reference's FP32 multiplication before the exponent rounding.
        volatile float raw=maximum*(1.0f/448.0f);
        float scale=std::exp2(std::ceil(std::log2(double(raw))));
        for(size_t j=0;j<32;++j) output[i+j]=bf16(nearest_fp8(f32(input[i+j])/scale)*scale);
    }
}
int main() {
    uint64_t checked=0;unsigned cases=0;uint32_t random=0x1017;
    for(size_t count : {size_t(32),size_t(64),size_t(256),size_t(4096),size_t(16*16384),size_t(32*16384),size_t(48*16384),size_t(2048*16384)}) {
        std::vector<uint16_t> input(count),expected(count),actual(count);
        for(size_t i=0;i<count;++i) {
            random^=random<<13;random^=random>>17;random^=random<<5;
            float v=float(int(random%8193)-4096)/128;
            v=std::ldexp(v,int((i/32)%41)-20);
            input[i]=bf16(v);
        }
        // All zero, tiny values, signed zeros, and halfway FP8 bins with scale=1.
        for(size_t i=0;i<std::min(count,size_t(32));++i) input[i]=uint16_t((i&1)<<15);
        if(count>=64) for(size_t i=32;i<64;++i) input[i]=bf16((i&1 ? -1 : 1)*1e-20f);
        if(count>=256) {
            for(size_t group=2;group<8;++group) {
                for(size_t j=0;j<31;++j) {
                    unsigned b=unsigned((group*17+j)%125);
                    float v=(fp8_value(b)+fp8_value(b+1))*0.5f;
                    input[group*32+j]=bf16(j&1 ? -v : v);
                }
                input[group*32+31]=bf16(448.0f);
            }
        }
        oracle(input,expected);
        uint16_t *original,*work;const size_t bytes=count*2;
        CHECK(cudaMalloc(&original,bytes));CHECK(cudaMalloc(&work,bytes));
        CHECK(cudaMemcpy(original,input.data(),bytes,cudaMemcpyHostToDevice));
        cudaStream_t stream;CHECK(cudaStreamCreate(&stream));
        auto launch=[&]() {
            CHECK(cudaMemcpyAsync(work,original,bytes,cudaMemcpyDeviceToDevice,stream));
            tf_ds_fp8_woa_kernel<<<std::min(size_t(65535),(count+255)/256),256,0,stream>>>((__nv_bfloat16*)work,count);
            CHECK(cudaGetLastError());
        };
        for(bool graph : {false,true}) {
            if(graph) {
                cudaGraph_t g;cudaGraphExec_t exec;
                CHECK(cudaStreamBeginCapture(stream,cudaStreamCaptureModeGlobal));launch();
                CHECK(cudaStreamEndCapture(stream,&g));CHECK(cudaGraphInstantiate(&exec,g,0));
                for(int repeat=0;repeat<3;++repeat) CHECK(cudaGraphLaunch(exec,stream));
                CHECK(cudaStreamSynchronize(stream));CHECK(cudaGraphExecDestroy(exec));CHECK(cudaGraphDestroy(g));
            } else {launch();CHECK(cudaStreamSynchronize(stream));}
            CHECK(cudaMemcpy(actual.data(),work,bytes,cudaMemcpyDeviceToHost));
            for(size_t i=0;i<count;++i) if(actual[i]!=expected[i]) {
                fprintf(stderr,"mismatch count=%zu graph=%d index=%zu input=%04x expected=%04x actual=%04x\n",count,int(graph),i,input[i],expected[i],actual[i]);return 1;
            }
            ++cases;checked+=count;
        }
        CHECK(cudaStreamDestroy(stream));CHECK(cudaFree(original));CHECK(cudaFree(work));
    }
    printf("{\"status\":\"passed\",\"cases\":%u,\"bf16_values_checked\":%llu,\"oracle\":\"enumerated E4M3 nearest-even with reference pow2 scales\",\"cuda_graphs\":true}\n",cases,(unsigned long long)checked);
}
