# ADR-010: Opt-in local AI4Bharat IndicF5 speech output

- Status: Accepted
- Date: 2026-09-11
- Supersedes: ADR-009 only for the set of supported TTS provider values

## Context

The kiosk's mock provider proves the HTTP and playback contract but emits an
acknowledgement tone rather than intelligible speech. The first IndicF5 attempt
loaded its checkpoint through the generic `f5_tts.api.F5TTS` interface, used an
unmatched or silent reference, silently substituted a different public model,
and downloaded artifacts during a patient request. Those behaviors caused long
request stalls and did not follow AI4Bharat's published model contract.

## Decision

- `mock` remains the default provider. `indicf5` is an explicit local profile.
- IndicF5 loads through `transformers.AutoModel.from_pretrained` with trusted
  remote code, a pinned model revision and a pinned AI4Bharat source package.
- The published `PAN_F_HAPPY_00001.wav` prompt is paired with its exact published
  transcript. Missing model or reference artifacts fail closed; there is no
  silent reference and no substitution with another model.
- Model loading can be completed before readiness with
  `TTS_WARMUP_ON_START=true`. Request execution has a bounded timeout and returns
  non-sensitive 503/504 errors while the visible text remains usable.
- Inductor compilation is disabled by default because it can cause a long or
  unsupported Windows compilation path. An eager `torch.compile` wrapper is
  retained because the published checkpoint stores trained weights under its
  `_orig_mod` key layout. This changes performance only, not model semantics.
- Reference preprocessing is completed once during warmup. The tested local
  latency profile uses 16 diffusion steps and exposes an 8–32 configuration
  range. A bounded per-process LRU cache prevents duplicate synthesis of common
  and prefetched patient prompts.
- The assisted-question client starts TTS prefetch as soon as clinical dialogue
  produces the next question, and `AudioPrompt` reuses the same in-flight request.
- The supported 6 GB GPU profile runs IndicF5 with `ASR_PROVIDER=mock` and
  `LLM_PROVIDER=mock`. Development reload workers are not used for this profile.
- The provider exposes unload behavior so the later S2S runtime coordinator can
  release its model before another GPU component starts.

## Verification on the target 6 GB GPU

On an RTX 3050 6 GB, three warm Hindi prompts took a median 11.95 seconds with
the upstream 32-step path and 5.94 seconds with the 16-step prepared-reference
path (about 50% lower latency). Peak allocated VRAM stayed at 1.37 GiB. A first
live HTTP synthesis took 9.51 seconds; the repeated cached request took 29.6 ms.
The generated prompt was then passed to AI4Bharat Indic Conformer in a separate
process after IndicF5 exited, which recovered the expected Hindi words. These
figures are a local benchmark, not a production service-level guarantee.

## Privacy and voice consent

Inference is local after model artifacts are downloaded. Generated clinical text
is not sent to Hugging Face. Patient audio is never used as reference audio by
this provider. Any replacement reference voice requires explicit permission from
the speaker, as required by the IndicF5 model terms.

## Consequences

The first startup requires gated model access, several gigabytes of dependencies
and model cache space, and can take minutes. A CUDA-enabled PyTorch installation
must be verified explicitly. IndicF5's published support covers 11 Indian
languages; English remains best-effort and cannot be represented as validated
production quality without a governed evaluation.
