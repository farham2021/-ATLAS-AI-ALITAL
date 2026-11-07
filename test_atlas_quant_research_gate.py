import unittest
from atlas_quant_research_gate import ResearchEvidence, assess, REQUIRED_CHECKS

def evidence(**changes):
    data=dict(strategy_id="low_vol",rule_version="original-v1",data_snapshot_id="pit-2026-11",
              benchmark="SP500-TR",trial_count=6,checks={k:True for k in REQUIRED_CHECKS},
              gross_sharpe=0.5,net_sharpe=0.3,out_of_sample_sharpe=0.2)
    data.update(changes)
    return ResearchEvidence(**data)

class QuantResearchGateTests(unittest.TestCase):
    def test_passes_to_paper_only(self):
        self.assertEqual(assess(evidence())["status"],"PAPER_TRADING")
    def test_validated_requires_paper(self):
        self.assertEqual(assess(evidence(paper_execution_verified=True))["status"],"VALIDATED")
    def test_missing_check_fails_closed(self):
        self.assertEqual(assess(evidence(checks={"data_integrity":True}))["status"],"RESEARCH_ONLY")
    def test_missing_oos_fails_closed(self):
        self.assertEqual(assess(evidence(out_of_sample_sharpe=None))["status"],"RESEARCH_ONLY")
    def test_nonpositive_net_or_oos_cannot_pass(self):
        self.assertEqual(assess(evidence(net_sharpe=-0.1))["status"],"RESEARCH_ONLY")
        self.assertEqual(assess(evidence(out_of_sample_sharpe=0))["status"],"RESEARCH_ONLY")
    def test_critical_bias_rejects(self):
        self.assertEqual(assess(evidence(critical_bias=True))["status"],"REJECTED")
    def test_data_integrity_false_rejects(self):
        self.assertEqual(assess(evidence(checks={"data_integrity":False}))["status"],"REJECTED")
    def test_invalid_trials(self):
        with self.assertRaises(ValueError): assess(evidence(trial_count=0))
    def test_no_live_execution(self):
        self.assertTrue(assess(evidence())["no_live_trading"])

if __name__=="__main__": unittest.main()
