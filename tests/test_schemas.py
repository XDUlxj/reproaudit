from reproaudit.models.claims import ScientificClaim


def test_scientific_claim():
    claim = ScientificClaim(
        text="Method X achieves 94.3% accuracy.",
        metric="accuracy",
        expected_value=94.3,
    )

    assert claim.metric == "accuracy"
    assert claim.expected_value == 94.3