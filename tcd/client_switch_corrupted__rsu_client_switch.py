# -*- coding: utf-8 -*-

import argparse
import logging
import re
import struct
import os

# Importing the public API Module
import fwval

#yi zhi's library
import fwval_lib

# Dictionary holding the opcode enumeration for mbox cmds
opcode = {
    "QSPI_READ": 58,
}

parser = argparse.ArgumentParser()
# Set MSEL and Power up DUT (AS Fast = b'1001; AS Normal = b'1011)
parser.add_argument('--msel', default="9", help='msel for DUT')
parser.add_argument('--pfg', help='pfg file name from parent test')
parser.add_argument('--corrupt', default="first4k", help='corrupt randomly at : first4k, signature_desc, ssbl, trampoline, main1_desc, main1_data, main2_desc, main2_data\n')
parser.add_argument('--c_image', default="P2", help='target image to be corrupted: FACTORY, P1, P2, P3')
parser.add_argument('--ff', default="", help='factory_fallback flag')
parser.add_argument('--switch', default="app2", help='app to switch -- factory, app1, app2, app3')
parser.add_argument('--factory_pin', default="sdmio_10", help='SDMIO Pin for LOADFACTORY\n')
parser.add_argument('--board_rev', default="RevB", help='board revision')
args = parser.parse_args()

msel_set = eval(args.msel)
if ((msel_set!=9) & (msel_set!=11)):
    fwval_lib.print_err("TEST :: Unsupported MSEL in this test - %d"% msel_set)
    exit(-2)
pfg_file = args.pfg
corrupt = args.corrupt
c_image = args.c_image
factory_fallback = args.ff
factory_pin = args.factory_pin
board_rev = args.board_rev
switch = args.switch
print("Set MSEL to: %d" % msel_set)
print("Set pfg_file to: %s" %  pfg_file)

# getsof() to get required bitstream files
jic_file,rpd_file,map_file,rbf_file = fwval_lib.execution_lib.getsof(input_file=pfg_file,mode="sof2rpd",conf="rsu")
[map_file, factory, app1, app2, app3] = fwval_lib.rpd_find_imagename(rpd_file)

if (switch == "app1"):
    assert app1 != "None", "ERROR :: switch is set to app1, but can't get the design name from rpd file"
elif (switch == "app2"):
    assert app2 != "None", "ERROR :: switch is set to app2, but can't get the design name from rpd file"
elif (switch == "app3"):
    assert app3 != "None", "ERROR :: switch is set to app3, but can't get the design name from rpd file"    
elif (switch == "factory"):
    assert factory != "None", "ERROR :: switch is set to factory, but can't get the design name from rpd file"     
def swap32(i):
    return struct.unpack("<I", struct.pack(">I", i))[0]

def main():
    dut_closed = False
    checks = []
    try:
        #setup test environment
        test = fwval_lib.RsuTest(msel=msel_set)
        test.drive_external_clock(external_clock_in_mhz=25)

        # Get connector for LOADFACTORY pin
        test.loadfactory = test.dut.get_connector(factory_pin)
        fwval_lib.assert_err(test.loadfactory != None, "ERROR :: Cannot open loadfactory (%s) Connector" %factory_pin)
        test.loadfactory.set_direction("out")
        
        # Drive LOADFactory pin 
        test.loadfactory.set_input(0)
        fwval_lib.assert_err(test.loadfactory.get_output()==0, "ERROR :: Load factory pin expected to be 0, but %d "%test.loadfactory.get_output())

        # Get FW address from .map file
        test.map_get_rsu_add(map_file)
        
        # Get more FW address from .rpd file
        bitstream = test.rpd_get_rsu_fw_add(rpd_file)
        
        # Write into reverse_file
        reverse_file = "reverse.rpd"
        fw1 = open(reverse_file, "wb")
        fw1.write(bitstream)
        fw1.close()

        #******************* MBR signature corruption started******************#
        acds_version = os.environ.get("ACDS_VERSION")
        dut_opn = os.environ['DUT_BASE_DIE']
        if(dut_opn=="FM7") and (fwval_lib.compare_quartus_version(acds_version , "22.1")==0):
            print("MBR signature corruption")
            # Prepare corrupted bitstream for MBR
            corrupted_mbr_bitstream = bytearray(bitstream)
            mbr_corrupt_offset = test.select_addr( location="mbr")
            corrupted_mbr_bitstream = test.corrupt_bitstream( corrupted_mbr_bitstream, offset=mbr_corrupt_offset, size=8)
            # Write into corrupted_file
            mbr_corrupted_file = "corrupted_mbr.rpd"
            fw1 = open(mbr_corrupted_file, "wb")
            fw1.write(corrupted_mbr_bitstream)
            fw1.close()
            
            # Set nconfig low
            test.power.set_power(False)
            test.nconfig.set_input(0)
            test.update_exp(nconfig=0, nstatus=0, config_done=0, init_done=0)
            
            # Write corrupted mbr bitstream into RAM
            test.prepare_qspi_rsu(file_path=mbr_corrupted_file, bitstream=corrupted_mbr_bitstream, offset=0, reverse=True)

            # Power up device and reset CSR
            test.power_up_reset()
            
            # Check pin
            checks.append(test.verify_pin(ast=0))

            # Drive nconfig => 1 and check result
            checks.extend( test.nconfig1_qspi(success=0, failed_cmf_state=0) )

            # Recover by using good bitstream
            # Set nconfig low
            test.power.set_power(False)
            test.nconfig.set_input(0)
            test.update_exp(nconfig=0, nstatus=0, config_done=0, init_done=0)
            
            # Write Good bitstream into RAM
            test.prepare_qspi_rsu(file_path=rpd_file, bitstream=bitstream, offset=0)

            # Power up device and reset CSR
            test.power_up_reset()
            
            # Check pin
            checks.append(test.verify_pin(ast=0))
            # Drive nconfig => 1 and check result
            checks.extend( test.nconfig1_qspi() )

        #******************* MBR signature corruption ended******************#
        
        # Prepare corrupted bitstream
        corrupted_bitstream = bytearray(bitstream)
        if ( re.search( r'P1', c_image) ):
            corrupt_image = "P1"
            
        if ( re.search( r'P2', c_image) ):
            corrupt_image = "P2"
            
        if ( re.search( r'P3', c_image) ):
            corrupt_image = "P3"
        
        corrupt_offset = test.select_addr( location=corrupt, image=corrupt_image)
        corrupted_bitstream = test.corrupt_bitstream( corrupted_bitstream, offset=corrupt_offset, size=1)
        
        # Write into corrupted_file
        corrupted_file = "corrupted.rpd"
        fw1 = open(corrupted_file, "wb")
        fw1.write(corrupted_bitstream)
        fw1.close()
        
        # Set nconfig low
        test.power.set_power(False)
        test.nconfig.set_input(0)
        test.update_exp(nconfig=0, nstatus=0, config_done=0, init_done=0)
        
        # Write corrupted bitstream into RAM
        test.prepare_qspi_rsu(file_path=corrupted_file, bitstream=corrupted_bitstream, offset=0, reverse=True)

        # Power up device and reset CSR
        test.power_up_reset()
        
        # Check pin
        checks.append(test.verify_pin(ast=0))
        
        # Configure QSPI prefetcher
        # if (switch == "app1"):
            # test.rsu_set_prefetcher(dcmf=1, cpb=0, factory=0, app1=1, app2=0, app3=0)
            # switch_offset = test.P1["START_ADD"]
            # switch_app = app1
        if (switch == "app2"):
            test.rsu_set_prefetcher(dcmf=1, cpb=0, factory=1, app1=1, app2=1, app3=0, extra=[test.P1["SSBL_START_ADD"] - test.P1["START_ADD"]])
            switch_offset = test.P2["START_ADD"]
            switch_app = app1
        # elif (switch == "app3"):
            # test.rsu_set_prefetcher(dcmf=1, cpb=0, factory=0, app1=1, app2=0, app3=1)
            # switch_offset = test.P3["START_ADD"]
            # switch_app = app3
        # elif (switch == "factory"):
            # test.rsu_set_prefetcher(dcmf=1, cpb=0, factory=1, app1=1, app2=0, app3=0)
            # switch_offset = test.FACTORY["START_ADD"]
            # switch_app = factory
                            
        # Drive nconfig => 1 and check result
        checks.extend( test.nconfig1_qspi() )

        #******************* MBR signature corruption started******************#     
        dut_opn = os.environ['DUT_BASE_DIE']
        if(dut_opn=="FM7") and (fwval_lib.compare_quartus_version(acds_version , "22.1")==0):
            status = test.qspi.qspi_open()
            fwval_lib.assert_err( status == 1,
                    "ERROR :: Unexpected qspi status after qspi_open" )
            status = status and test.qspi.qspi_set_cs(0)

            fwval_lib.assert_err( status == 1,
                    "ERROR :: Unexpected qspi status after qspi_set_cs" )
            response = test.jtag_send_sdmcmd(opcode["QSPI_READ"], 504, 10)
            print("Value at 510 and 511 is {:08x}".format(swap32(response[2]) & 0xFFFF))
            fwval_lib.assert_err( (swap32(response[2])) & 0xFFFF == 0x55AA,
                    "ERROR :: There are no MBR partition in qspi flash" )

            status = status and test.qspi.qspi_close()
            fwval_lib.assert_err( status == 1,
                    "ERROR :: Unexpected qspi status after update existing image" )
            print("MBR verification is passed")
        #******************* MBR signature corruption ended******************#
        
        # Verify design
        #if (app1=="None"):
            #checks.append(test.verify_design( design_name=factory, ast=1 ))
        #else:
            #checks.append(test.verify_design( design_name=app1, ast=1 ))
        
        # verify RSU status
        test.update_exp_rsu(current_image=test.P1["START_ADD"])
        checks.append(test.verify_rsu_status())
        
        # Switch image
        test.rsu_switch_image(switch_offset)
        fwval_lib.delay(1000)
        #test.verify_qspi_bfm_status()
        
        # verify RSU status
        if (factory_fallback == "ff"):
            test.update_exp_rsu(current_image=test.FACTORY["START_ADD"], last_fail_image=switch_offset, state=1)	
        else:
            test.update_exp_rsu(current_image=test.P1["START_ADD"], last_fail_image=switch_offset, state=1)
        # test.update_exp_rsu(current_image=test.P1["START_ADD"])
        checks.append(test.verify_rsu_status())
        
        # verify design
        #checks.append(test.verify_design( design_name=switch_app, ast=0 ))
        
        #check pin and status verification (if didn't assert them)
        for check in checks:
            assert check==1, "ERROR :: One or more of the pin/status verifications failed"

        #close dut, set it as empty test
        print("\nClose DUT")
        test.dut.close()
        dut_closed = True
        
        #check if any sys-console left and kill them
        fwval.delay(1000)
        fwval_lib.kill_all_syscon()
        exit(0)

    except Exception as e:
        # only call qspi bfm read when configuration is failed. Detail refer to 15011347718
        test.verify_qspi_bfm_status()
        
        fwval_lib.print_err("\nREPORT :: FAILED due to Exception")

        #log the traceback into stderr
        logging.exception('')
        
        # main error handler
        test.main_error_handler(dut_closed)
        
        exit(-1)
        
main()
