import unittest

from shared.admission.canary import occupy_capacity


class CanaryCapacityTests(unittest.TestCase):
    def exercise(self,hardware,slots,fleet):
        active={'fleet':0,'interactive':0,'auxiliary':0}
        streams=[]
        def admitted(role):
            return (sum(active.values())<slots and
                    (hardware!='rtx5080' or role=='auxiliary') and
                    (role not in ('fleet','auxiliary') or hardware=='rtx5080' or active['fleet']<fleet))
        def request(role):
            self.assertTrue(admitted(role),'canary attempted a request beyond live capacity')
            active[role]+=1
            return object()
        def reject(role,status):
            self.assertEqual(status,429)
            self.assertFalse(admitted(role),'canary expected overflow before filling live capacity')
        role,first=occupy_capacity(hardware,{'slots':slots,'agents':fleet},request,reject,streams)
        self.assertEqual(len(streams),slots)
        self.assertIs(first,streams[0])
        return role,active

    def test_six_slot_geekom_fills_four_fleet_and_two_interactive(self):
        role,active=self.exercise('geekom',6,4)
        self.assertEqual(role,'fleet')
        self.assertEqual(active,{'fleet':4,'interactive':2,'auxiliary':0})

    def test_three_slot_geekom_reserves_two_interactive(self):
        self.assertEqual(self.exercise('geekom',3,1)[1]['interactive'],2)

    def test_rtx_only_accepts_auxiliary(self):
        self.assertEqual(self.exercise('rtx5080',1,0)[1]['auxiliary'],1)


if __name__=='__main__':unittest.main()
