from fwval_lib.common import *
from fwval_lib.configuration.jtag import JtagTest
import binascii
import cv_logger
import execution_lib
import os
import pycv as fwval
import random
import re

revision = "$Revision: #14 $"
__version__ = 0
try: __version__ = int([''.join([str(s) for s in [c for c in revision] if s.isdigit()])][0])
except: pass
cv_logger.info("%s current rev: #%s" % (__name__, __version__))
cv_logger.info("%s source: %s" % (__name__, __file__))

###########################################################################################
#    QSPI
###########################################################################################

#QspiTest will support all JtagTest capabilities, with addition of Qspi ones as defined here
class QspiTest(JtagTest):
    '''
        Input   : configuration, msel, for fwval.platform_init(), default None and 8 respectively
                  config_done_sdmio, init_done_sdmio, have default values 16 and 0
                  rev -- used for specify revision (string contain a,b,c, etc). if don't care
                         then leave at empty string
                  daughter_card -- Set dc=1 if the test is using a physical QSPI flash. If no value is
                                   given, Sdmio Class will auto assign a value based on the platform
        Mod     : self -- initialize the test object
        Note    : the rev variable is used when there are differences between revisions.
                  eg. for RevA, CONFIG_STATUS command will fail at IDLE state. So we must
                  input RevA when our test call CONFIG_STATUS in IDLE state.
                  (I recommend putting your rev in, you may forget that RevA does not work
                  in some cases. At least the code will tell you)
    '''
    def __init__(self, configuration="qspi", msel=9, rev="", daughter_card=None, config_done_sdmio="", init_done_sdmio=None):
        #calls the super constructor (JtagTest constructor)
        self._sdmio = Sdmio(msel=msel, configuration=configuration, daughter_card=daughter_card,dut_sdm_conf_done=config_done_sdmio)

        '''
        external flash daughter card enabled or not
        disabled - oscar/emulator
        enabled  - mudv
        '''
        if self._sdmio.platform in ['oscar', 'emulator', 'simics', 'oscarbb']:
            self.daughter_card = False
        elif self._sdmio.platform == 'mudv':
            self.daughter_card = True
        else:
            raise 'Unsupported Platform in QSPI'
        super(QspiTest, self).__init__(configuration=configuration, msel=msel, rev=rev, daughter_card=self.daughter_card,
            config_done_sdmio=config_done_sdmio, init_done_sdmio=init_done_sdmio)

        #gets the remaining connectors
        self.qspi = self.dut.get_connector("qspi")
        self._lib_delay()
        assert_err(self.qspi != None, "ERROR :: Cannot open the QSPI Connector")

        self.sdm = self.dut.get_connector("sdm")
        assert_err(self.sdm != None, "ERROR :: Cannot open the SDM Connector")

    '''
    Input   : nconfig: the nconfig value that the board will turn on with
    Optional: nconfig will be set to 1 by default
    Req     : nconfig must be 1 or 0
    Mod     : self -- power cycle the board (off, set nconfig, on)
    '''
    def power_cycle(self, nconfig=1):
        #power off
        cv_logger.info("Power off")
        self.power.set_power(False)
        self._fuse_write_disabled = False
        #toggle the nconfig pin
        cv_logger.info("Set nconfig = %d" %nconfig)
        self.nconfig.set_input(nconfig)
        self._lib_delay()
        #power on
        cv_logger.info("Power on")
        self.power_up_reset()

    '''
    Input   : en -- enables the check for the specific pins (1 enable, 0 disable)
              ast -- if 1, throws assertion when pin mismatch. if 0, no assertion just output
    Optional: en=1, disable as required
              ast=0, enable as required
    Output  : True if correct, False if incorrect
    Same with verify_pin for JtagTest, but with different default value for avst_ready_en
    '''
    def verify_pin(self, nstatus_en=1, init_done_en=0, config_done_en=1, ast=0, log_error=1,index="", wait_time_out_check=False):
        return super(QspiTest, self).verify_pin(nstatus_en=nstatus_en, init_done_en=init_done_en,
            config_done_en=config_done_en, ast=ast, log_error=log_error, index=index, wait_time_out_check=wait_time_out_check)


    '''
    Modify  : Read Trace address
    '''
    def read_address_error12(self) :
        CSR_ADD_ERROR12 = 0x24004
        master_service = self.qspi.platform.get_bfm_master_service()
        assert_err(len(master_service), "ERROR :: Failed to get master path")
        command = "master_read_32 %s 0x%08X 1" % (master_service, CSR_ADD_ERROR12)
        respond = self.qspi.platform.send_system_console(command)
        cv_logger.info("Read QSPI CSR for address that cause BFM STATUS 0xC: %s" %respond )
        return respond

    '''
    Modify  : Verify QSPI BFM Status, assert error if BFM status is not 1
    '''
    def verify_qspi_bfm_status(self):
        #skip this step whenever running on mudv platform
        if self._sdmio.platform == 'mudv':
            cv_logger.info("Skip to verify qspi bfm status on mudv platform")
            return
        [prefetcher_busy, bfm_status] = self.qspi.read_csr()
        cv_logger.info("Prefetcher Busy = %d" % prefetcher_busy)
        cv_logger.info("BFM status = %d" % bfm_status)
        if (bfm_status == 12):
            # trace address cause storage failure
            self.read_address_error12()

        if (bfm_status == 4):
            [cqd, ced, rpa] = self.qspi.read_csr_debug()
            cv_logger.info("Read QSPI CSR for address that cause BFM STATUS_4 cqd:0x%X, ced:0x%X, rpa:0x%X" %(cqd, ced, rpa))
            #cv_logger.info("cqd:0x%X ced:0x%X rpa:0x%X" % (cqd, ced, rpa))


        assert_err( bfm_status == 1,
            "ERROR :: Unexpected QSPI BFM CSR status : %d" %bfm_status )

    '''
    Modify  : different power up reset sequence in different platform
              - mudv   (with external flash daughter card)
              - oscar  (without daughter card)
    '''
    def power_up_reset(self, cmf_copy=1, puf_enable=0):
        if self._sdmio.platform in ['oscar', 'emulator', 'simics', 'oscarbb']:
            self.power_up_reset_bfm(cmf_copy=cmf_copy, puf_enable=puf_enable)
        elif self._sdmio.platform == 'mudv':
            self.power_up_reset_daughter_card()
        else:
            raise 'Unsupported Platform in QSPI'


    '''
    Modify  : perform power up reset sequence in mudv platform with external flash daughter card
    '''
    def power_up_reset_daughter_card(self):
        self.power.set_power(False)
        delay(1000)
        self.power.set_power(True)

    '''
    Modify  : Power up DUT, Reset CSR upon power up and Configure data prefetcher
              puf_enable -- to enable puf data adition into the prefetcher list
                         -- 1 = Decryption (Block 0)
                         -- 2 = Corruption (Block 0 -> block 1 Recover)
                         -- 3 = JTAG Activation
    '''
    def power_up_reset_bfm(self, cmf_copy=1, puf_enable=0):
        # Power up dut
        self.power.set_power(True)

        # Reset CSR upon power up
        cv_logger.info("Reset CSR upon power up")
        self.qspi.write_csr(True, False)
        #self.verify_qspi_bfm_status()
        # [prefetcher_busy, bfm_status] = self.qspi.read_csr()
        # cv_logger.info("Prefetcher Busy = %d" % prefetcher_busy)
        # cv_logger.info("BFM status = %d" % bfm_status)
        # assert_err( bfm_status == 1,
            # "ERROR :: Unexpected QSPI BFM CSR status : %d" %bfm_status )

        # Configure data prefetcher
        if hasattr(self, 'SSBL_START_ADD'):
            ssbl_add1 = self.SSBL_START_ADD
        else:
            cv_logger.warning("Assume SSBL start address: 0xa000")
            # Assume SSBL start add  = 0xa000
            ssbl_add1 = 0xa000

        # Needed for HPS cold reset use case where SDM skips the FBRC section (first section) and directly loads HPS section (second section)
        # Checks if there are two main sections present and stores the address of second main section in main_sec_2_addr
        if(self.DUT_FAMILY == "diamondmesa"):
            if (hasattr(self, 'MAIN_ADD')) and (len(self.MAIN_ADD) > 2):
                main_sec_2_addr = self.MAIN_ADD[2]
            else:
                cv_logger.info("Main Section 2 not present")
                main_sec_2_addr = 0x0
        
        # Define current acds version & build
        acds_version = os.environ.get("ACDS_VERSION")
        acds_build = float(os.environ.get("ACDS_BUILD_NUMBER"))

        if cmf_copy == 1:
            if(os.environ.get("FWVAL_PLATFORM") == 'emulator' or "agilex" in self.DUT_FAMILY or self.DUT_FAMILY == "diamondmesa"):
                if(self.DUT_FAMILY == "diamondmesa"):
                    if(((compare_quartus_version("22.1",acds_version)==0 and acds_build >= 140) or (compare_quartus_version(acds_version , "22.1")==1)) and self.DUT_FAMILY != "stratix10"):
                        # This adds the address Of second main section (which is HPS section for DM) to QSPI prefetcher
                        cv_logger.info("Configure QSPI prefetcher with: 0x0, 0x1BC, 0x200000, 0x80000, 0x100000, 0x180000,  0x%x, 0x%x, 0x%x"%(ssbl_add1, MAIN_IMAGE_POINTER['puf_data_0'][0], MAIN_IMAGE_POINTER['puf_data_1'][0]))
                        self.qspi.set_prefetcher(0x0, 0x1BC, 0x200000, 0x80000, 0x100000, 0x180000, MAIN_IMAGE_POINTER['puf_data_0'][0], MAIN_IMAGE_POINTER['puf_data_1'][0], ssbl_add1, main_sec_2_addr)
                    else:
                        # This adds the address Of second main section (which is HPS section for DM) to QSPI prefetcher
                        cv_logger.info("Configure QSPI prefetcher with: 0x0, 0x200000, 0x80000, 0x100000, 0x180000,  0x%x, 0x%x, 0x%x"%(ssbl_add1, MAIN_IMAGE_POINTER['puf_data_0'][0], MAIN_IMAGE_POINTER['puf_data_1'][0]))
                        self.qspi.set_prefetcher(0x0, 0x200000, 0x80000, 0x100000, 0x180000, MAIN_IMAGE_POINTER['puf_data_0'][0], MAIN_IMAGE_POINTER['puf_data_1'][0], ssbl_add1, main_sec_2_addr)
                else:
                    if(((compare_quartus_version("22.1",acds_version)==0 and acds_build >= 140) or (compare_quartus_version(acds_version , "22.1")==1)) and self.DUT_FAMILY != "stratix10"):
                        cv_logger.info("Configure QSPI prefetcher with: 0x1BC, 0x200000, 0x80000, 0x100000, 0x180000,  0x%x, 0x%x, 0x%x"%(ssbl_add1, MAIN_IMAGE_POINTER['puf_data_0'][0], MAIN_IMAGE_POINTER['puf_data_1'][0]))
                        self.qspi.set_prefetcher(0x1BC, 0x200000, 0x200008, 0x80000, 0x100000, 0x180000, MAIN_IMAGE_POINTER['puf_data_0'][0], MAIN_IMAGE_POINTER['puf_data_1'][0], ssbl_add1)
                    else:
                        cv_logger.info("Configure QSPI prefetcher with: 0x0, 0x200000, 0x80000, 0x100000, 0x180000,  0x%x, 0x%x, 0x%x"%(ssbl_add1, MAIN_IMAGE_POINTER['puf_data_0'][0], MAIN_IMAGE_POINTER['puf_data_1'][0]))
                        self.qspi.set_prefetcher(0x0, 0x200000, 0x200008, 0x80000, 0x100000, 0x180000, MAIN_IMAGE_POINTER['puf_data_0'][0], MAIN_IMAGE_POINTER['puf_data_1'][0], ssbl_add1)
				# PUF_ENABLE = 1 : Generic ASX4 Decryption (BLK 1)
                if puf_enable == 1:

                        puf0_data         = self.iid_puf_addr.PUF_ADD[1]
                        help0_data_offset = self.iid_puf_addr.HELP_DATA_OFFSET[1]
                        wkey0_data_offset = self.iid_puf_addr.WKEY_DATA_OFFSET[1]
                        help0_data        = self.iid_puf_addr.PUF_DATA_ADDR[1]
                        wkey0_data        = self.iid_puf_addr.PUF_WKEY_ADDR[1]
                        core0_data        = self.MAIN_ADD[1]
                        core1_data        = self.MAIN_ADD[2]
                        if(((compare_quartus_version("22.1",acds_version)==0 and acds_build >= 140) or (compare_quartus_version(acds_version , "22.1")==1)) and self.DUT_FAMILY != "stratix10"):
                            cv_logger.info("PUF ENABLED - Configure QSPI prefetcher with: 0x0, 0x1BC, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x" %(self.SYNC_START_ADD+1, ssbl_add1, puf0_data, help0_data_offset, wkey0_data_offset, help0_data, wkey0_data, core0_data, core1_data, core0_data+0x2000, core1_data+0x2000))
                            self.qspi.set_prefetcher(0x0, 0x1BC, self.SYNC_START_ADD+1, ssbl_add1, puf0_data, help0_data_offset, wkey0_data_offset, 0x200010, 0x200014, help0_data, wkey0_data, 0x208008, 0x203000, 0x204000, 0x208010, core0_data, core1_data, core0_data+0x2000, core1_data+0x2000)
                        else:
                            cv_logger.info("PUF ENABLED - Configure QSPI prefetcher with: 0x0, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x" %(self.SYNC_START_ADD+1, ssbl_add1, puf0_data, help0_data_offset, wkey0_data_offset, help0_data, wkey0_data, core0_data, core1_data, core0_data+0x2000, core1_data+0x2000))
                            self.qspi.set_prefetcher(0x0, self.SYNC_START_ADD+1, ssbl_add1, puf0_data, help0_data_offset, wkey0_data_offset, 0x200010, 0x200014, help0_data, wkey0_data, 0x208008, 0x203000, 0x204000, 0x208010, core0_data, core1_data, core0_data+0x2000, core1_data+0x2000)
            # PUF_ENABLE = 2 : Activation Corruption Case
                if puf_enable == 2:
                    # Address to add into prefetcher
                    # a) 0x0 & SSBL
                    # b) HELP DATA0,1 BASE   i.e. 100000,108000
                    # c) HELP DATA0,1 OFFSET i.e. 100008,108008
                    # d) HELP DATA0,1        i.e. 101000,109000
                    # e) Core Data for boot (MAIN , IO)
                    puf0_data         = self.iid_puf_addr.PUF_ADD[1]
                    puf1_data         = self.iid_puf_addr.PUF_ADD[2]
                    help0_data_offset = self.iid_puf_addr.HELP_DATA_OFFSET[1]
                    help1_data_offset = self.iid_puf_addr.HELP_DATA_OFFSET[2]
                    help0_data        = self.iid_puf_addr.PUF_DATA_ADDR[1]
                    help1_data        = self.iid_puf_addr.PUF_DATA_ADDR[2]
                    core0_data = self.MAIN_ADD[1]
                    if(((compare_quartus_version("22.1",acds_version)==0 and acds_build >= 140) or (compare_quartus_version(acds_version , "22.1")==1)) and self.DUT_FAMILY != "stratix10"):
                        cv_logger.info("PUF ENABLED - Configure QSPI prefetcher with: 0x0, 0x1BC, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x" %(self.SYNC_START_ADD+1, ssbl_add1, puf0_data, puf1_data, help0_data_offset, help1_data_offset, help0_data, help1_data, core0_data))
                        self.qspi.set_prefetcher(0x0, 0x1BC, self.SYNC_START_ADD+1, ssbl_add1, puf0_data, puf1_data, help0_data_offset, help1_data_offset, 0x200010, help0_data, help1_data, core0_data)
                    else:
                        cv_logger.info("PUF ENABLED - Configure QSPI prefetcher with: 0x0, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x" %(self.SYNC_START_ADD+1, ssbl_add1, puf0_data, puf1_data, help0_data_offset, help1_data_offset, help0_data, help1_data, core0_data))
                        self.qspi.set_prefetcher(0x0, self.SYNC_START_ADD+1, ssbl_add1, puf0_data, puf1_data, help0_data_offset, help1_data_offset, 0x200010, help0_data, help1_data, core0_data)
                # PUF_ENABLE = 3 : Activation (JTAG) Case
                if puf_enable == 3:
                    # Address to add into prefetcher
                    # a) SSBL
                    # b) MIP PUF0,1          i.e. 1F90,1F98
                    # c) HELP DATA0,1 BASE   i.e. 100000,108000
                    # d) HELP DATA0,1 OFFSET i.e. 100008,108008
                    # e) HELP DATA0,1        i.e. 101000,109000
                    puf0_data         = self.iid_puf_addr.PUF_ADD[1]
                    mip0_data         = self.iid_puf_addr.PUF_OFFSET[1]
                    mip1_data         = self.iid_puf_addr.PUF_OFFSET[2]
                    puf0_data         = self.iid_puf_addr.PUF_ADD[1]
                    puf1_data         = self.iid_puf_addr.PUF_ADD[2]
                    help0_data_offset = self.iid_puf_addr.HELP_DATA_OFFSET[1]
                    help1_data_offset = self.iid_puf_addr.HELP_DATA_OFFSET[2]
                    help0_data        = self.iid_puf_addr.PUF_DATA_ADDR[1]
                    help1_data        = self.iid_puf_addr.PUF_DATA_ADDR[2]
                    if(((compare_quartus_version("22.1",acds_version)==0 and acds_build >= 140) or (compare_quartus_version(acds_version , "22.1")==1)) and self.DUT_FAMILY != "stratix10"):
                        cv_logger.info("PUF ENABLED - Configure QSPI prefetcher with: 0x1BC, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x" %(self.SYNC_START_ADD+1, ssbl_add1, mip0_data, mip1_data, puf0_data, puf1_data, help0_data_offset, help1_data_offset, help0_data, help1_data))
                        self.qspi.set_prefetcher(0x1BC, self.SYNC_START_ADD+1, ssbl_add1, mip0_data, mip1_data, puf0_data, puf1_data, help0_data_offset, help1_data_offset, help0_data, help1_data)
                    else:
                        cv_logger.info("PUF ENABLED - Configure QSPI prefetcher with: 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x" %(self.SYNC_START_ADD+1, ssbl_add1, mip0_data, mip1_data, puf0_data, puf1_data, help0_data_offset, help1_data_offset, help0_data, help1_data))
                        self.qspi.set_prefetcher(self.SYNC_START_ADD+1, ssbl_add1, mip0_data, mip1_data, puf0_data, puf1_data, help0_data_offset, help1_data_offset, help0_data, help1_data)



            else:
                if(((compare_quartus_version("22.1",acds_version)==0 and acds_build >= 140) or (compare_quartus_version(acds_version , "22.1")==1)) and self.DUT_FAMILY != "stratix10"):
                    cv_logger.info("Configure QSPI prefetcher with: 0x0, 0x1BC, 0x100000, 0x40000, 0x80000, 0xc0000,  0x%x, 0x%x, 0x%x"%(ssbl_add1, MAIN_IMAGE_POINTER['puf_data_0'][0], MAIN_IMAGE_POINTER['puf_data_1'][0]))
                    self.qspi.set_prefetcher(0x0, 0x1BC, 0x100000, 0x40000, 0x80000, 0xc0000, MAIN_IMAGE_POINTER['puf_data_0'][0], MAIN_IMAGE_POINTER['puf_data_1'][0], ssbl_add1)
                else:
                    cv_logger.info("Configure QSPI prefetcher with: 0x0, 0x100000, 0x40000, 0x80000, 0xc0000,  0x%x, 0x%x, 0x%x"%(ssbl_add1, MAIN_IMAGE_POINTER['puf_data_0'][0], MAIN_IMAGE_POINTER['puf_data_1'][0]))
                    self.qspi.set_prefetcher(0x0, 0x100000, 0x40000, 0x80000, 0xc0000, MAIN_IMAGE_POINTER['puf_data_0'][0], MAIN_IMAGE_POINTER['puf_data_1'][0], ssbl_add1)

                # PUF_ENABLE = 1 : Generic ASX4 Decryption (BLK 1)
                if puf_enable == 1:
                    # Address to add into prefetcher
                    # a) 0x0 & SSBL
                    # b) HELP DATA0 BASE   i.e. 100000
                    # c) HELP DATA0 OFFSET i.e. 100008
                    # d) WKEY DATA0 OFFSET i.e. 10000C
                    # e) HELP DATA0        i.e. 101000
                    # f) WKEY DATA0        i.e. 102000
                    # g) Core Data for boot (MAIN , IO)
                    # h) AES Key Data      i.e. Core + 2000
                    puf0_data         = self.iid_puf_addr.PUF_ADD[1]
                    help0_data_offset = self.iid_puf_addr.HELP_DATA_OFFSET[1]
                    wkey0_data_offset = self.iid_puf_addr.WKEY_DATA_OFFSET[1]
                    help0_data        = self.iid_puf_addr.PUF_DATA_ADDR[1]
                    wkey0_data        = self.iid_puf_addr.PUF_WKEY_ADDR[1]
                    core0_data        = self.MAIN_ADD[1]
                    core1_data        = self.MAIN_ADD[2]
                    if(((compare_quartus_version("22.1",acds_version)==0 and acds_build >= 140) or (compare_quartus_version(acds_version , "22.1")==1)) and self.DUT_FAMILY != "stratix10"):
                        cv_logger.info("PUF ENABLED - Configure QSPI prefetcher with: 0x0, 0x1BC, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x" %(self.SYNC_START_ADD+1, ssbl_add1, puf0_data, help0_data_offset, wkey0_data_offset, help0_data, wkey0_data, core0_data, core1_data, core0_data+0x2000, core1_data+0x2000))
                        self.qspi.set_prefetcher(0x0, 0x1BC, self.SYNC_START_ADD+1, ssbl_add1, puf0_data, help0_data_offset, wkey0_data_offset, help0_data, wkey0_data, core0_data, core1_data, core0_data+0x2000, core1_data+0x2000)
                    else:
                        cv_logger.info("PUF ENABLED - Configure QSPI prefetcher with: 0x0, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x" %(self.SYNC_START_ADD+1, ssbl_add1, puf0_data, help0_data_offset, wkey0_data_offset, help0_data, wkey0_data, core0_data, core1_data, core0_data+0x2000, core1_data+0x2000))
                        self.qspi.set_prefetcher(0x0, self.SYNC_START_ADD+1, ssbl_add1, puf0_data, help0_data_offset, wkey0_data_offset, help0_data, wkey0_data, core0_data, core1_data, core0_data+0x2000, core1_data+0x2000)
                # PUF_ENABLE = 2 : Activation Corruption Case
                if puf_enable == 2:
                    # Address to add into prefetcher
                    # a) 0x0 & SSBL
                    # b) HELP DATA0,1 BASE   i.e. 100000,108000
                    # c) HELP DATA0,1 OFFSET i.e. 100008,108008
                    # d) HELP DATA0,1        i.e. 101000,109000
                    # e) Core Data for boot (MAIN , IO)
                    puf0_data         = self.iid_puf_addr.PUF_ADD[1]
                    puf1_data         = self.iid_puf_addr.PUF_ADD[2]
                    help0_data_offset = self.iid_puf_addr.HELP_DATA_OFFSET[1]
                    help1_data_offset = self.iid_puf_addr.HELP_DATA_OFFSET[2]
                    help0_data        = self.iid_puf_addr.PUF_DATA_ADDR[1]
                    help1_data        = self.iid_puf_addr.PUF_DATA_ADDR[2]
                    core0_data = self.MAIN_ADD[1]
                    if(((compare_quartus_version("22.1",acds_version)==0 and acds_build >= 140) or (compare_quartus_version(acds_version , "22.1")==1)) and self.DUT_FAMILY != "stratix10"):
                        cv_logger.info("PUF ENABLED - Configure QSPI prefetcher with: 0x0, 0x1BC, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x" %(self.SYNC_START_ADD+1, ssbl_add1, puf0_data, puf1_data, help0_data_offset, help1_data_offset, help0_data, help1_data, core0_data))
                        self.qspi.set_prefetcher(0x0, 0x1BC, self.SYNC_START_ADD+1, ssbl_add1, puf0_data, puf1_data, help0_data_offset, help1_data_offset, help0_data, help1_data, core0_data)
                    else:
                        cv_logger.info("PUF ENABLED - Configure QSPI prefetcher with: 0x0, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x" %(self.SYNC_START_ADD+1, ssbl_add1, puf0_data, puf1_data, help0_data_offset, help1_data_offset, help0_data, help1_data, core0_data))
                        self.qspi.set_prefetcher(0x0, self.SYNC_START_ADD+1, ssbl_add1, puf0_data, puf1_data, help0_data_offset, help1_data_offset, help0_data, help1_data, core0_data)
                # PUF_ENABLE = 3 : Activation (JTAG) Case
                if puf_enable == 3:
                    # Address to add into prefetcher
                    # a) SSBL
                    # b) MIP PUF0,1          i.e. 1F90,1F98
                    # c) HELP DATA0,1 BASE   i.e. 100000,108000
                    # d) HELP DATA0,1 OFFSET i.e. 100008,108008
                    # e) HELP DATA0,1        i.e. 101000,109000
                    puf0_data         = self.iid_puf_addr.PUF_ADD[1]
                    mip0_data         = self.iid_puf_addr.PUF_OFFSET[1]
                    mip1_data         = self.iid_puf_addr.PUF_OFFSET[2]
                    puf0_data         = self.iid_puf_addr.PUF_ADD[1]
                    puf1_data         = self.iid_puf_addr.PUF_ADD[2]
                    help0_data_offset = self.iid_puf_addr.HELP_DATA_OFFSET[1]
                    help1_data_offset = self.iid_puf_addr.HELP_DATA_OFFSET[2]
                    help0_data        = self.iid_puf_addr.PUF_DATA_ADDR[1]
                    help1_data        = self.iid_puf_addr.PUF_DATA_ADDR[2]
                    if(((compare_quartus_version("22.1",acds_version)==0 and acds_build >= 140) or (compare_quartus_version(acds_version , "22.1")==1)) and self.DUT_FAMILY != "stratix10"):
                        cv_logger.info("PUF ENABLED - Configure QSPI prefetcher with: 0x1BC, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x" %(self.SYNC_START_ADD+1, ssbl_add1, mip0_data, mip1_data, puf0_data, puf1_data, help0_data_offset, help1_data_offset, help0_data, help1_data))
                        self.qspi.set_prefetcher(0x1BC, self.SYNC_START_ADD+1, ssbl_add1, mip0_data, mip1_data, puf0_data, puf1_data, help0_data_offset, help1_data_offset, help0_data, help1_data)
                    else:
                        cv_logger.info("PUF ENABLED - Configure QSPI prefetcher with:  0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x" %(self.SYNC_START_ADD+1, ssbl_add1, mip0_data, mip1_data, puf0_data, puf1_data, help0_data_offset, help1_data_offset, help0_data, help1_data))
                        self.qspi.set_prefetcher(self.SYNC_START_ADD+1, ssbl_add1, mip0_data, mip1_data, puf0_data, puf1_data, help0_data_offset, help1_data_offset, help0_data, help1_data)


        elif cmf_copy == 2:
            if(os.environ.get("FWVAL_PLATFORM") == 'emulator' or "agilex" in self.DUT_FAMILY or self.DUT_FAMILY == "diamondmesa"):
                if(((compare_quartus_version("22.1",acds_version)==0 and acds_build >= 140) or (compare_quartus_version(acds_version , "22.1")==1)) and self.DUT_FAMILY != "stratix10"):
                    cv_logger.info("Configure QSPI prefetcher with: 0x0, 0x1BC, 0x200000, 0x80000, 0x100000, 0x180000, 0x%x, 0x%x"%(ssbl_add1, ssbl_add1 + 0x80000))
                    self.qspi.set_prefetcher(0x0, 0x1BC, 0x200000, 0x80000, 0x100000, 0x180000, ssbl_add1, ssbl_add1 + 0x80000)
                else:
                    cv_logger.info("Configure QSPI prefetcher with: 0x0, 0x200000, 0x80000, 0x100000, 0x180000, 0x%x, 0x%x"%(ssbl_add1, ssbl_add1 + 0x80000))
                    self.qspi.set_prefetcher(0x0, 0x200000, 0x80000, 0x100000, 0x180000, ssbl_add1, ssbl_add1 + 0x80000)
            else:
                if(((compare_quartus_version("22.1",acds_version)==0 and acds_build >= 140) or (compare_quartus_version(acds_version , "22.1")==1)) and self.DUT_FAMILY != "stratix10"):
                    cv_logger.info("Configure QSPI prefetcher with: 0x0, 0x1BC, 0x100000, 0x40000, 0x80000, 0xc0000, 0x%x, 0x%x"%(ssbl_add1, ssbl_add1 + 0x40000))
                    self.qspi.set_prefetcher(0x0, 0x1BC, 0x100000, 0x40000, 0x80000, 0xc0000, ssbl_add1, ssbl_add1 + 0x40000)
                else:
                    cv_logger.info("Configure QSPI prefetcher with: 0x0, 0x100000, 0x40000, 0x80000, 0xc0000, 0x%x, 0x%x"%(ssbl_add1, ssbl_add1 + 0x40000))
                    self.qspi.set_prefetcher(0x0, 0x100000, 0x40000, 0x80000, 0xc0000, ssbl_add1, ssbl_add1 + 0x40000)

        elif cmf_copy == 3:
            if(os.environ.get("FWVAL_PLATFORM") == 'emulator' or "agilex" in self.DUT_FAMILY or self.DUT_FAMILY == "diamondmesa"):
                if(((compare_quartus_version("22.1",acds_version)==0 and acds_build >= 140) or (compare_quartus_version(acds_version , "22.1")==1)) and self.DUT_FAMILY != "stratix10"):
                    cv_logger.info("Configure QSPI prefetcher with: 0x0, 0x1BC, 0x200000, 0x80000, 0x100000, 0x180000, 0x%x, 0x%x, 0x%x"%(ssbl_add1, ssbl_add1 + 0x80000, ssbl_add1 + 0x100000))
                    self.qspi.set_prefetcher(0x0, 0x1BC, 0x200000, 0x80000, 0x100000, 0x180000, ssbl_add1, ssbl_add1 + 0x80000, ssbl_add1 + 0x100000)
                else:
                    cv_logger.info("Configure QSPI prefetcher with: 0x0, 0x200000, 0x80000, 0x100000, 0x180000, 0x%x, 0x%x, 0x%x"%(ssbl_add1, ssbl_add1 + 0x80000, ssbl_add1 + 0x100000))
                    self.qspi.set_prefetcher(0x0, 0x200000, 0x80000, 0x100000, 0x180000, ssbl_add1, ssbl_add1 + 0x80000, ssbl_add1 + 0x100000)
            else:
                if(((compare_quartus_version("22.1",acds_version)==0 and acds_build >= 140) or (compare_quartus_version(acds_version , "22.1")==1)) and self.DUT_FAMILY != "stratix10"):
                    cv_logger.info("Configure QSPI prefetcher with: 0x0, 0x1BC, 0x100000, 0x40000, 0x80000, 0xc0000, 0x%x, 0x%x, 0x%x"%(ssbl_add1, ssbl_add1 + 0x40000, ssbl_add1 + 0x80000))
                    self.qspi.set_prefetcher(0x0, 0x1BC, 0x100000, 0x40000, 0x80000, 0xc0000, ssbl_add1, ssbl_add1 + 0x40000, ssbl_add1 + 0x80000)
                else:
                    cv_logger.info("Configure QSPI prefetcher with: 0x0, 0x100000, 0x40000, 0x80000, 0xc0000, 0x%x, 0x%x, 0x%x"%(ssbl_add1, ssbl_add1 + 0x40000, ssbl_add1 + 0x80000))
                    self.qspi.set_prefetcher(0x0, 0x100000, 0x40000, 0x80000, 0xc0000, ssbl_add1, ssbl_add1 + 0x40000, ssbl_add1 + 0x80000)

        elif cmf_copy == 4:
            if(os.environ.get("FWVAL_PLATFORM") == 'emulator' or "agilex" in self.DUT_FAMILY or self.DUT_FAMILY == "diamondmesa"):
                if(((compare_quartus_version("22.1",acds_version)==0 and acds_build >= 140) or (compare_quartus_version(acds_version , "22.1")==1)) and self.DUT_FAMILY != "stratix10"):
                    cv_logger.info("Configure QSPI prefetcher with: 0x0, 0x1BC, 0x200000, 0x80000, 0x100000, 0x180000, 0x%x, 0x%x, 0x%x, 0x%x"%(ssbl_add1, ssbl_add1 + 0x80000, ssbl_add1 + 0x100000, ssbl_add1 + 0x180000))
                    self.qspi.set_prefetcher(0x0, 0x1BC, 0x200000, 0x80000, 0x100000, 0x180000, ssbl_add1, ssbl_add1 + 0x80000, ssbl_add1 + 0x100000, ssbl_add1 + 0x180000)
                else:
                    cv_logger.info("Configure QSPI prefetcher with: 0x0, 0x200000, 0x80000, 0x100000, 0x180000, 0x%x, 0x%x, 0x%x, 0x%x"%(ssbl_add1, ssbl_add1 + 0x80000, ssbl_add1 + 0x100000, ssbl_add1 + 0x180000))
                    self.qspi.set_prefetcher(0x0, 0x200000, 0x80000, 0x100000, 0x180000, ssbl_add1, ssbl_add1 + 0x80000, ssbl_add1 + 0x100000, ssbl_add1 + 0x180000)
            else:
                if(((compare_quartus_version("22.1",acds_version)==0 and acds_build >= 140) or (compare_quartus_version(acds_version , "22.1")==1)) and self.DUT_FAMILY != "stratix10"):
                    cv_logger.info("Configure QSPI prefetcher with: 0x0, 0x1BC, 0x100000, 0x40000, 0x80000, 0xc0000, 0x%x, 0x%x, 0x%x, 0x%x"%(ssbl_add1, ssbl_add1 + 0x40000, ssbl_add1 + 0x80000, ssbl_add1 + 0xc0000))
                    self.qspi.set_prefetcher(0x0, 0x1BC, 0x100000, 0x40000, 0x80000, 0xc0000, ssbl_add1, ssbl_add1 + 0x40000, ssbl_add1 + 0x80000, ssbl_add1 + 0xc0000)
                else:
                    cv_logger.info("Configure QSPI prefetcher with: 0x0, 0x100000, 0x40000, 0x80000, 0xc0000, 0x%x, 0x%x, 0x%x, 0x%x"%(ssbl_add1, ssbl_add1 + 0x40000, ssbl_add1 + 0x80000, ssbl_add1 + 0xc0000))
                    self.qspi.set_prefetcher(0x0, 0x100000, 0x40000, 0x80000, 0xc0000, ssbl_add1, ssbl_add1 + 0x40000, ssbl_add1 + 0x80000, ssbl_add1 + 0xc0000)
                #cv_logger.info("Configure QSPI prefetcher with: 0x0, 0x1BC, 0x100000, 0x40000, 0x80000, 0xc0000, 0x%x, 0x%x, 0x%x, 0x%x"%(ssbl_add1, ssbl_add1 + 0x40000, ssbl_add1 + 0x80000, ssbl_add1 + 0xc0000))
                #self.qspi.set_prefetcher(0x0, 0x1BC, 0x100000, 0x40000, 0x80000, 0xc0000, ssbl_add1, ssbl_add1 + 0x40000, ssbl_add1 + 0x80000, ssbl_add1 + 0xc0000)
        else:
            cv_logger.info("Unsupported cmf_copy")


        #self.verify_qspi_bfm_status()
        # [prefetcher_busy, bfm_status] = self.qspi.read_csr()
        # cv_logger.info("Prefetcher Busy = %d" % prefetcher_busy)
        # cv_logger.info("BFM status = %d" % bfm_status)
        # assert_err( bfm_status == 1,
            # "ERROR :: Unexpected QSPI BFM CSR status : %d" %bfm_status )


    '''
    Modify  : different prepare qspi sequence in different platform
              - mudv   (with external flash daughter card)
              - oscar  (without daughter card)
    '''
    def prepare_qspi(self, file_path, bitstream=None,  chip_select=0, offset=0, verify=0, check_ram=1, ast=0, read_ssbl=0, timeout=120, reverse=False, reconfig=0, puf_enable = 0, skip_extract = 0):
        
        if file_path!=None and skip_extract == 0:
            conf_done = extract_pin_table(file_path=file_path, pin_name="CONF_DONE")
            if conf_done != None :
                self.config_done = self.dut.get_connector(conf_done,self._DEVICE_IDX)
                self._CONFIG_DONE = conf_done

        if self._sdmio.platform in ['oscar', 'emulator', 'simics', 'oscarbb']:
            self.prepare_qspi_using_bfm(file_path, offset=offset, check_ram=check_ram, ast=ast, read_ssbl=read_ssbl, timeout=timeout, puf_enable = puf_enable)
        elif self._sdmio.platform == 'mudv':
            cv_logger.info('Running on MUDV Platform')

            if file_path and bitstream:
                cv_logger.info('WARNING :: bitstream is ignored because file_path and bitstream is defined at the same time')

            # to add bitstream support in https://hsdes.intel.com/appstore/article/#/16012856244
            # reverse will always opposite when there is rpd vs no rpd
            # to avoid massive change on rsu test content which already ported to mudv
            if not file_path:
                cv_logger.info('convert bitstream to rpd file ...')
                file_path='temp.rpd'
                self.write_bitstream_to_file(bitstream, start=0, end=len(bitstream), file_path=file_path)
                if skip_extract == 0:
                    conf_done = extract_pin_table(file_path=file_path, pin_name="CONF_DONE")
                    if conf_done != None :
                        self.config_done = self.dut.get_connector(conf_done,self._DEVICE_IDX)
                        self._CONFIG_DONE = conf_done
                reverse = not reverse

            self.prepare_qspi_using_daughter_card(rpd=file_path, chip_select=chip_select, offset=offset, verify=verify, reverse=reverse, reconfig=reconfig)
        else:
            raise 'Unsupported Platform in QSPI'


    '''
    Input   : rpd -- rpd to send into flash
    Optional: offset -- 0 the start address of flash
              chip select -- 0 Write the value of the flash device you want to select.
              verify -- 0 verify the data after write rpd into flash
    Modify  : send rpd into daughter card flash
              1. program helper via jtag
              2. qspi open
              3. qspi chip select
              4. qspi erase flash from address of (offset + rpd size)
              5. qspi write rpd into flash from address of offset
              6. qspi close
    Output  : None
    '''
    def prepare_qspi_using_daughter_card(self, rpd, chip_select=0, offset=0, verify=0, reverse=False, reconfig=0):

        if reconfig == 1:
            cv_logger.info("Skip to program helper during reconfiguration")
        else:
            cv_logger.info("Prepare DUT helper image...")
            helper = execution_lib.getsof(input_sof_flag=0,input_file='or_gate_design.x4.77MHZ_IOSC.sof',mode="sof2rbf", conf="qspi")
            # helper = 'or_gate_design.x4.77MHZ_IOSC.dc.AGFB014R24A2E2VR0.0341A0DD-20.4_b52.rbf'
            pem_file = "iid_puf/auth_keys/agilex_ec_priv_384_test.pem"
            qky_file = "iid_puf/auth_keys/agilex_ec_384_test.qky"
            signed_helper = "signed_helper_file.rbf"

            if (os.path.exists(pem_file) and os.path.exists(qky_file)):
                cv_logger.info("Use signed helper image instead of unsigned helper image")
                run_command("quartus_sign --family=agilex --operation=sign --pem=%s --qky=%s %s %s" %(pem_file,qky_file,helper,signed_helper))
                helper = signed_helper

            self.power.set_power(True)
            self.config_jtag()
            self.send_jtag(file_path=helper, success=1, timeout=60)

        status = self.qspi.qspi_open()
        assert_err( status==1,
            "ERROR :: Failed to open QSPI interface")

        # Set Chip Select to decide which daughter card
        status = self.qspi.qspi_set_cs(chip_select)
        assert_err( status==1,
            "ERROR :: Failed to chip select qspi")

        # most of the corruption test will reverse the data before send bitstream to flash
        # here is way to reverse back into correct order to avoid massive test change
        if reverse:
            file_obj = open(rpd, "rb")
            assert_err( file_obj, "ERROR :: Failed to Open the file %s" %rpd)

            bitstream = bytearray(file_obj.read())
            file_obj.close()

            reversed_bitstream = reverse_bitstream(bitstream)

            writer = open(rpd, "wb")
            writer.write(reversed_bitstream)
            writer.close()


        cv_logger.info("QSPI program %s"% rpd)
        self.dut.test_time()
        status = status and self.qspi.qspi_program(rpd, offset, verify=verify)
        assert_err(status == True,
                "ERROR :: Unexpected QSPI verify status : %d" %status )
        cv_logger.info("Time to program rpd: %s" % self.dut.elapsed_time())

        # Close exclusive access to QSPI interface
        response = self.qspi.qspi_close()
        assert_err(response,
            "ERROR :: Fail to close QSPI Interface access")


    '''
    Input   : file_path -- path for the bitstream file (usually rbf file)
              ast -- 1 if ast for check_ram(), 0 otherwise
              read_ssbl -- 1 to read bitstream for SSBl start address; 0 to skip read if already read once
    Optional: check_ram -- 1 if want to check the bitstream written into RAM, if not 0
    Modify  : self, prepares AVST configuration by writing bitstream into RAM
    Output  : returns the length of the bitstream (number of bytes)
    '''
    def prepare_qspi_using_bfm(self, file_path, offset=0, check_ram=1, ast=0, read_ssbl=0, timeout=120, puf_enable=0):

        #read bitstream into byte array
        bitstream = self.read_bitstream(file_path)

        # Read SSBL start address based on the bitstream
        if not read_ssbl:
            if not hasattr(self, 'SSBL_START_ADD'):
                self.rpd_get_ssbl_add(bitstream)
        else:
            # Read SSBL add
            self.rpd_get_ssbl_add(bitstream)

            # Read trampoline add
            self.rpd_get_trampoline_add(bitstream)

        #prepare the RAM
        cv_logger.info("Writing Bistream into RAM for QSPI...")
        self.dut.test_time()
        if(os.environ.get("FWVAL_PLATFORM") == 'emulator'):
            timeout=300
        self.qspi.prepare_data(bitstream, offset, True, timeout)
        cv_logger.info("Time to write data into RAM: %s" % self.dut.elapsed_time())
        #if user specified, check the RAM bistream
        if check_ram:
            self.check_ram(bitstream=bitstream, ast=ast)
        else:
            cv_logger.warning("QSPI RAM bitstream not checked")
            delay(3000)

        # Define current acds version & build
        acds_version = os.environ.get("ACDS_VERSION")
        acds_build = float(os.environ.get("ACDS_BUILD_NUMBER"))

        # Configure QSPI prefetcher if read_ssbl is enabled
        if read_ssbl:
            ssbl_add1 = self.SSBL_START_ADD
            trampoline_end_add = self.TRAMPOLINE_END_ADD # Trampoline address is checked from the bitstream
            if(os.environ.get("FWVAL_PLATFORM") == 'emulator' or "agilex" in self.DUT_FAMILY or self.DUT_FAMILY == "diamondmesa"):
                if(((compare_quartus_version("22.1",acds_version)==0 and acds_build >= 140) or (compare_quartus_version(acds_version , "22.1")==1)) and self.DUT_FAMILY != "stratix10"):
                    cv_logger.info("QSPI set prefetcher 0x1BC, 0x200000, 0x80000, 0x100000, 0x180000, puf_data_0, puf_data_1, ssbl_add1, ssbl_add1 + 0x80000, ssbl_add1 + 0x100000, ssbl_add1 + 0x180000, trampoline_end_add")
                    cv_logger.info("QSPI set prefetcher 0x1BC, 0x200000, 0x80000, 0x100000, 0x180000, 0x%x, 0x%x, 0x%x,  0x%x,  0x%x,  0x%x, 0x%x" % (MAIN_IMAGE_POINTER['puf_data_0'][0],  MAIN_IMAGE_POINTER['puf_data_1'][0], ssbl_add1, ssbl_add1 + 0x80000, ssbl_add1 + 0x100000, ssbl_add1 + 0x180000, trampoline_end_add))
                    self.qspi.set_prefetcher(0x1BC, 0x200000, 0x80000, 0x100000, 0x180000, MAIN_IMAGE_POINTER['puf_data_0'][0],  MAIN_IMAGE_POINTER['puf_data_1'][0], ssbl_add1, ssbl_add1 + 0x80000, ssbl_add1 + 0x100000, ssbl_add1 + 0x180000, trampoline_end_add)
                else:
                    cv_logger.info("QSPI set prefetcher 0x0, 0x200000, 0x80000, 0x100000, 0x180000, puf_data_0, puf_data_1, ssbl_add1, ssbl_add1 + 0x80000, ssbl_add1 + 0x100000, ssbl_add1 + 0x180000, trampoline_end_add")
                    cv_logger.info("QSPI set prefetcher 0x0, 0x200000, 0x80000, 0x100000, 0x180000, 0x%x, 0x%x, 0x%x,  0x%x,  0x%x,  0x%x, 0x%x" % (MAIN_IMAGE_POINTER['puf_data_0'][0],  MAIN_IMAGE_POINTER['puf_data_1'][0], ssbl_add1, ssbl_add1 + 0x80000, ssbl_add1 + 0x100000, ssbl_add1 + 0x180000, trampoline_end_add))
                    self.qspi.set_prefetcher(0x0, 0x200000, 0x80000, 0x100000, 0x180000, MAIN_IMAGE_POINTER['puf_data_0'][0],  MAIN_IMAGE_POINTER['puf_data_1'][0], ssbl_add1, ssbl_add1 + 0x80000, ssbl_add1 + 0x100000, ssbl_add1 + 0x180000, trampoline_end_add)
                # PUF_ENABLE = 1 : Generic ASX4 Decryption (BLK 1)
                if puf_enable == 1:
                    puf0_data         = self.iid_puf_addr.PUF_ADD[1]
                    help0_data_offset = self.iid_puf_addr.HELP_DATA_OFFSET[1]
                    wkey0_data_offset = self.iid_puf_addr.WKEY_DATA_OFFSET[1]
                    help0_data        = self.iid_puf_addr.PUF_DATA_ADDR[1]
                    wkey0_data        = self.iid_puf_addr.PUF_WKEY_ADDR[1]
                    core0_data        = self.MAIN_ADD[1]
                    core1_data        = self.MAIN_ADD[2]
                    if(((compare_quartus_version("22.1",acds_version)==0 and acds_build >= 140) or (compare_quartus_version(acds_version , "22.1")==1)) and self.DUT_FAMILY != "stratix10"):
                        cv_logger.info("PUF ENABLED - Configure QSPI prefetcher with: 0x0, 0x1BC, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x" %(self.SYNC_START_ADD+1, ssbl_add1, puf0_data, help0_data_offset, wkey0_data_offset, help0_data, wkey0_data, core0_data, core1_data, core0_data+0x2000, core1_data+0x2000))
                        self.qspi.set_prefetcher(0x0, 0x1BC, self.SYNC_START_ADD+1, ssbl_add1, puf0_data, help0_data_offset, wkey0_data_offset, 0x200010, 0x200014, help0_data, wkey0_data, 0x203000, 0x204000, 0x208010, core0_data, core1_data, core0_data+0x2000, core1_data+0x2000)
                    else:
                        cv_logger.info("PUF ENABLED - Configure QSPI prefetcher with: 0x0, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x" %(self.SYNC_START_ADD+1, ssbl_add1, puf0_data, help0_data_offset, wkey0_data_offset, help0_data, wkey0_data, core0_data, core1_data, core0_data+0x2000, core1_data+0x2000))
                        self.qspi.set_prefetcher(0x0, self.SYNC_START_ADD+1, ssbl_add1, puf0_data, help0_data_offset, wkey0_data_offset, 0x200010, 0x200014, help0_data, wkey0_data, 0x203000, 0x204000, 0x208010, core0_data, core1_data, core0_data+0x2000, core1_data+0x2000)

            else:
                if(((compare_quartus_version("22.1",acds_version)==0 and acds_build >= 140) or (compare_quartus_version(acds_version , "22.1")==1)) and self.DUT_FAMILY != "stratix10"):
                    cv_logger.info("QSPI set prefetcher 0x0, 0x1BC, 0x100000, 0x40000, 0x80000, 0xc0000, puf_data_0, puf_data_1, ssbl_add1, ssbl_add1 + 0x40000, ssbl_add1 + 0x80000, ssbl_add1 + 0xc0000, trampoline_end_add")
                    cv_logger.info("QSPI set prefetcher 0x0, 0x1BC, 0x100000, 0x40000, 0x80000, 0xc0000, 0x%x, 0x%x, 0x%x,  0x%x,  0x%x,  0x%x, 0x%x"% (MAIN_IMAGE_POINTER['puf_data_0'][0],  MAIN_IMAGE_POINTER['puf_data_1'][0], ssbl_add1, ssbl_add1 + 0x40000, ssbl_add1 + 0x80000, ssbl_add1 + 0xc0000, trampoline_end_add))
                    self.qspi.set_prefetcher(0x0, 0x1BC, 0x100000, 0x40000, 0x80000, 0xc0000, MAIN_IMAGE_POINTER['puf_data_0'][0], MAIN_IMAGE_POINTER['puf_data_1'][0], ssbl_add1, ssbl_add1 + 0x40000, ssbl_add1 + 0x80000, ssbl_add1 + 0xc0000, trampoline_end_add)
                else:
                    cv_logger.info("QSPI set prefetcher 0x0, 0x100000, 0x40000, 0x80000, 0xc0000, puf_data_0, puf_data_1, ssbl_add1, ssbl_add1 + 0x40000, ssbl_add1 + 0x80000, ssbl_add1 + 0xc0000, trampoline_end_add")
                    cv_logger.info("QSPI set prefetcher 0x0, 0x100000, 0x40000, 0x80000, 0xc0000, 0x%x, 0x%x, 0x%x,  0x%x,  0x%x,  0x%x, 0x%x"% (MAIN_IMAGE_POINTER['puf_data_0'][0],  MAIN_IMAGE_POINTER['puf_data_1'][0], ssbl_add1, ssbl_add1 + 0x40000, ssbl_add1 + 0x80000, ssbl_add1 + 0xc0000, trampoline_end_add))
                    self.qspi.set_prefetcher(0x0, 0x100000, 0x40000, 0x80000, 0xc0000, MAIN_IMAGE_POINTER['puf_data_0'][0], MAIN_IMAGE_POINTER['puf_data_1'][0], ssbl_add1, ssbl_add1 + 0x40000, ssbl_add1 + 0x80000, ssbl_add1 + 0xc0000, trampoline_end_add)

                # PUF_ENABLE = 1 : Generic ASX4 Decryption (BLK 1)
                if puf_enable == 1:
                    # Address to add into prefetcher
                    # a) 0x0 & SSBL
                    # b) HELP DATA0 BASE   i.e. 100000
                    # c) HELP DATA0 OFFSET i.e. 100008
                    # d) WKEY DATA0 OFFSET i.e. 10000C
                    # e) HELP DATA0        i.e. 101000
                    # f) WKEY DATA0        i.e. 102000
                    # g) Core Data for boot (MAIN , IO)
                    # h) AES Key Data      i.e. Core + 2000
                    puf0_data         = self.iid_puf_addr.PUF_ADD[1]
                    help0_data_offset = self.iid_puf_addr.HELP_DATA_OFFSET[1]
                    wkey0_data_offset = self.iid_puf_addr.WKEY_DATA_OFFSET[1]
                    help0_data        = self.iid_puf_addr.PUF_DATA_ADDR[1]
                    wkey0_data        = self.iid_puf_addr.PUF_WKEY_ADDR[1]
                    core0_data        = self.MAIN_ADD[1]
                    core1_data        = self.MAIN_ADD[2]
                    if((compare_quartus_version("22.1",acds_version)==0 and acds_build >= 140) or (compare_quartus_version(acds_version , "22.1")==1)):
                        cv_logger.info("PUF ENABLED - Configure QSPI prefetcher with: 0x0, 0x1BC, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x" %(ssbl_add1, puf0_data, help0_data_offset, wkey0_data_offset, help0_data, wkey0_data, core0_data, core1_data, core0_data+0x2000, core1_data+0x2000))
                        self.qspi.set_prefetcher(0x0, 0x1BC, ssbl_add1, puf0_data, help0_data_offset, wkey0_data_offset, help0_data, wkey0_data, core0_data, core1_data, core0_data+0x2000, core1_data+0x2000)
                    else:
                        cv_logger.info("PUF ENABLED - Configure QSPI prefetcher with: 0x0, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x, 0x%x" %(ssbl_add1, puf0_data, help0_data_offset, wkey0_data_offset, help0_data, wkey0_data, core0_data, core1_data, core0_data+0x2000, core1_data+0x2000))
                        self.qspi.set_prefetcher(0x0, ssbl_add1, puf0_data, help0_data_offset, wkey0_data_offset, help0_data, wkey0_data, core0_data, core1_data, core0_data+0x2000, core1_data+0x2000)

        cv_logger.info("Finished preparing QSPI")

        return len(bitstream)