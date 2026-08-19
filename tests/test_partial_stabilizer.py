from voicepaste.partial_stabilizer import PartialTranscriptStabilizer


def test_partial_stabilizer_holds_back_tail_words() -> None:
    stabilizer = PartialTranscriptStabilizer(hold_back_words=2)

    display, stable = stabilizer.ingest("hello world this is")
    assert display == "hello world this is"
    assert stable == ""

    display, stable = stabilizer.ingest("hello world this is a test")
    assert display == "hello world this is a test"
    assert stable == "hello world"

    display, stable = stabilizer.ingest("hello world this was a test")
    assert display == "hello world this was a test"
    assert stable == "hello world"


def test_partial_stabilizer_grows_stable_prefix_only_forward() -> None:
    stabilizer = PartialTranscriptStabilizer(hold_back_words=1)
    stabilizer.ingest("open github repo")
    _, stable = stabilizer.ingest("open github repo and push")
    assert stable == "open github"
    _, stable = stabilizer.ingest("open github repo and push now")
    assert stable.startswith("open github")
