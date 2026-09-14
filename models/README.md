# Model registry

`models/registry/` holds the trained models. **Nothing under it is committed**
(the root `.gitignore` ignores `models/registry/**`): the artefacts are a pure
function of the committed processed parquet, the code and `model.seed`, so
`make train` reproduces them byte for byte instead of git storing them
(ADR-022). Training both plants takes well under a minute.

## Regenerate

```sh
make train        # uv run python scripts/train.py --plant all
make evaluate     # uv run python scripts/evaluate.py  -> docs/EVALUATION.md
```

`scripts/train.py --plant ai4i|ims|all` trains one or both plants;
`--bump major|minor|patch` writes a new version instead of overwriting the
newest one; `--models-dir` points the whole thing at another registry root.
Re-running without `--bump` is idempotent.

## Layout

```
models/registry/
  current -> ai4i/lgbm/1.0.0        # the default plant's served model
  ai4i/
    current -> lgbm/1.0.0           # this plant's served family and version
    lgbm/1.0.0/
      model.txt            LightGBM native text booster (deterministic bytes)
      feature_names.json   the ordered feature vector; the serving contract
      feature_meta.json    display name, unit, framing, window and stat per feature
      background.parquet   the frozen 256-row interventional SHAP background
      metrics.json         held-out metrics + the calibration diagnostic
      model_card.md        what this model is, what it is not
      manifest.json        identity, seed, digests, split and training window
    rf/1.0.0/              the comparison model; model.joblib instead of model.txt
  ims/ ...
```

One directory per plant because the two plants have different channels and
therefore different feature vectors — 154 features for `ai4i`, 198 for `ims`.
`current` is a relative symlink at both levels, so a rollback is one command:

```sh
ln -sfn lgbm/1.0.0 models/registry/ai4i/current
```

## What is not here

There is **no calibrator**, of any kind, in any version directory. The served
model's own probability is the number the pipeline thresholds, the dashboard
prints and the SHAP waterfall sums to (R16, ADR-016). Calibration quality is
reported as a diagnostic in `docs/EVALUATION.md` and, if it is poor, is fixed in
training. A `calibrator.joblib` appearing under `models/registry/**` is a bug,
and `tests/model/test_registry.py` fails if one does.

## Loading a model

Use the registry API rather than opening files directly — it validates the
feature contract before returning anything, and a model whose feature order
disagrees with `xpm.features.registry` is refused rather than served:

```python
from xpm.model import registry

entry = registry.resolve_version(registry.registry_root(), "ai4i")   # served model
booster = registry.load_model(entry)                                 # validates first
background = registry.load_background(entry)                         # for TreeExplainer
manifest = registry.validate_version(entry)                          # n_features, seed, digests
```
