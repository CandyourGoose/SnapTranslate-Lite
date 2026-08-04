# PP-OCRv5 model provenance

These runtime assets were prepared on 2026-08-01 from PaddleOCR's official
PP-OCRv5 mobile inference models.

## Sources

- Detection: `https://paddle-model-ecology.bj.bcebos.com/paddlex/official_inference_model/paddle3.0.0/PP-OCRv5_mobile_det_infer.tar`
- Recognition: `https://paddle-model-ecology.bj.bcebos.com/paddlex/official_inference_model/paddle3.0.0/PP-OCRv5_mobile_rec_infer.tar`
- Dictionary: `https://raw.githubusercontent.com/PaddlePaddle/PaddleOCR/v3.5.0/ppocr/utils/dict/ppocrv5_dict.txt`

## Conversion

- PaddlePaddle `3.1.1`
- Paddle2ONNX `2.1.0`
- ONNX opset `17`
- ONNX checker enabled
- Optional graph optimizer disabled because it hung on the Windows conversion
  host; the unoptimized graphs pass ONNX checker and ONNX Runtime loading.

## SHA-256

| File | SHA-256 |
| --- | --- |
| `PP-OCRv5_mobile_det.onnx` | `C8D9B07063420CE5365C74E42532DE48238FEEEEDCDB7A330B195708BC38A93F` |
| `PP-OCRv5_mobile_rec.onnx` | `BCB195E3463EB9E46EF419B8A01EA4729577DE5FD63C64F0A762E43BD64256E7` |
| `ppocrv5_dict.txt` | `D1979E9F794C464C0D2E0B70A7FE14DD978E9DC644C0E71F14158CDF8342AF1B` |

PaddleOCR and its model assets are provided under the
[Apache License 2.0](https://github.com/PaddlePaddle/PaddleOCR/blob/v3.5.0/LICENSE).

No PixPin binary, DLL, model, key, or extracted weight is included.
