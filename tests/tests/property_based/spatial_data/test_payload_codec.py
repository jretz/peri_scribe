"""Arbitrary bytes retain their complete representation through compressed frames."""

import hypothesis
import hypothesis.strategies

import spatial_data.payload_codec
import spatial_data.payload_prediction


@hypothesis.given(hypothesis.strategies.binary(max_size=8192))
def test_prediction_and_codec_preserve_arbitrary_binary_values(value: bytes) -> None:
    predicted = spatial_data.payload_prediction.predict(value)
    assert spatial_data.payload_prediction.restore(predicted, len(value)) == value
    for predictor in spatial_data.payload_codec.Predictor:
        encoded = spatial_data.payload_codec.encode(value, predictor=predictor)
        assert spatial_data.payload_codec.decode(encoded) == value
