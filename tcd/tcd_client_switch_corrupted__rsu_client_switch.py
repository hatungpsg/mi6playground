Here are the comments inserted with '##' label for better understanding of the code:

```python
# -*- coding: utf-8 -*-

import argparse
import logging
import re
import os
import struct

# Importing the public API Module
import fwval

# Dictionary holding the opcode enumeration for mbox cmds
opcode = {
    "QSPI_READ": 58,
}

#yi zhi's library
import fwval_lib

## Creating a parser to handle command line arguments
parser = argparse.ArgumentParser()
# Set MSEL and Power up DUT (AS Fast = b'1001; AS Normal = b'1011)
parser.add_argument('--msel', default="9", help='msel for DUT')
parser.add_argument('--pfg', help='pfg file name from parent test')
parser.add_argument('--switch', default="after_end", help='app to switch -- after_end, mid_app1')
parser.add_argument('--factory_pin', default="sdmio_16", help='SDMIO Pin for LOADFACTORY\n')
parser.add_argument('--board_rev', default="RevB", help='board revision')
args = parser.parse_args()

## Parsing the command line arguments
pfg_file = args.pfg
msel_set = eval(args.msel)
if ((msel_set!=9) & (msel_set!=11)):
    fwval_lib.print_err("TEST :: Unsupported MSEL in this test - %d"% msel_set)
    exit(-2)
factory_pin = args.factory_pin
board_rev = args.board_rev
switch = args.switch

## Printing the MSEL and PFG file
print("Set MSEL to: %d" % msel_set)
print("Set pfg_file to: %s" %  pfg_file)

## Getsof() to get required bitstream files
jic_file,rpd_file,map_file,rbf_file = fwval_lib.execution_lib.getsof(input_file=pfg_file,mode="sof2rpd",conf="rsu")

## Finding the image names from the RPD file
[map_file, factory, app1, app2, app3] = fwval_lib.rpd_find_imagename(rpd_file)

## Getting map & jic file to be used for test
#/ Expect 1 Map file, 1 Jic file & few RPD files, depending on no of CS enabled
for root, dirs, files in os.walk("./"):
    for file in files:
        if file.endswith(".map"):
            map_file = file
        if file.endswith(".jic"):
            jic_file = file
print("Map file ---> %s" %map_file)
print("Jic file ---> %s" %jic_file)

## Function for swapping 32 bit integers
def swap32(i):
    return struct.unpack("<I", struct.pack(">I", i))[0]
    
def main():
    dut_closed = False
    checks = []
    try:
        ## Setup test environment
        #/ Msel set to RSU & external clock driven in 25Mhz
        if ((board_rev == "RevC") | (board_rev == "RevA")):
            test = fwval_lib.RsuTest(msel=msel_set)
        elif ((board_rev == "RevB") | (board_rev == "nd4_RevA")):
            test = fwval_lib.RsuTest(msel=15)
        else:
            print("WARNING :: Unknown board revision")
            test = fwval_lib.RsuTest(msel=msel_set)
            
        test.drive_external_clock(external_clock_in_mhz=25)    
            
        ## Get connector for LOADFACTORY pin & drive LOADFactory pin to 0
        test.loadfactory = test.dut.get_connector(factory_pin)
        fwval_lib.assert_err(test.loadfactory != None, "ERROR :: Cannot open loadfactory (%s) Connector" %factory_pin)
        test.loadfactory.set_direction("out")
        
        test.loadfactory.set_input(0)
        fwval_lib.assert_err(test.loadfactory.get_output()==0, "ERROR :: Load factory pin expected to be 0, but %d "%test.loadfactory.get_output())

        ## Get FW address from .map file
        #/ Getting Factory, P1 Images addresses for start & end
        test.map_get_rsu_add(map_file)
        
        ## Power up device and reset CSR
        test.power_up_reset()
               
        ## Perform JIC Programming using Quartus PGM command
        #/ Finish JIC programming successfully & print out total time taken for the programming activity
        test.dut.test_time()
        test.dut.close_platform()
              
        fwval_lib.run_command("quartus_pgm -c %d -m JTAG -o \"pi;%s\"" % (test.dut.dut_cable, jic_file), timeout=9000)
        test.dut.msg("Time to perform JIC programming: %s" % test.dut.elapsed_time())
        test.dut.open_platform()
        
        ## Power down, set nconfig 0, delay 2000ms
        test.power.set_power(False)
        if ((board_rev == "RevB") | (board_rev == "nd4_RevA")):
            test.power.set_msel_value(msel_set)
            test.update_exp(msel=msel_set)
            
        test.nconfig.set_input(0)
        fwval_lib.delay(2000)
        
        ## Power up device and reset CSR
        test.power_up_reset()
        
        ## Configure QSPI prefetcher for BFM
        test.rsu_set_prefetcher(dcmf=1, cpb=0, factory=1, app1=1, app2=1, app3=0)
        
        ## Configure QSPI Switch Offset, parameter is passed in from parent test
        if (switch == "spt1_start_add"):
            switch_offset = test.SPT1_START_ADD
            test.rsu_set_prefetcher(dcmf=1, cpb=0, factory=1, app1=1, app2=1, app3=0, extra=[switch_offset, 0xa000])
        elif (switch == "after_end"):
            switch_offset = test.P1_END_ADD
            test.rsu_set_prefetcher(dcmf=1, cpb=0, factory=1, app1=1, app2=1, app3=0, extra=[switch_offset, 0xa000])
        
        ## Drive nconfig to 1 to trigger configuration from QSPI flash
        checks.extend( test.nconfig1_qspi() )

        #******************* MBR signature verification started******************#     
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
        #******************* MBR signature verification ended******************# 
               
        ## Verify design
        if (app1=="None"):
            checks.append(test.verify_design( design_name=factory, ast=1 ))
        else:
            checks.append(test.verify_design( design_name=app1, ast=1 ))
        
        ## Verify RSU boot up from P1 Image
        test.update_exp_rsu(current_image=test.P1_START_ADD)
        checks.append(test.verify_rsu_status())
        
        ## Attempt RSU Switch image to a non-existent image
        #/ Expect fail to boot from the switch image & P1 image is used for boot up
        test.rsu_switch_image(switch_offset)
        fwval_lib.delay(1000)
        
        ## Verify RSU boot up from P1 Image & last failed image states switch offset value
        test.update_exp_rsu(current_image=test.P1_START_ADD, last_fail_image=switch_offset, state=1)
        checks.append(test.verify_rsu_status())
        
        ## Verify design that is currently running match with P1 Image Design
        checks.append(test.verify_design( design_name=app1, ast=0 ))

        ## Check pin and status verifications
        for check in checks:
            assert check==1, "ERROR :: One or more of the pin/status verifications failed"

        ## Close DUT
        print("\nClose DUT")
        test.dut.close()
        dut_closed = True
       
        ## Delay 1000ms, check if any sys-console left and kill them all
        fwval.delay(1000)
        fwval_lib.kill_all_syscon()
        exit(0)

    except Exception as e:
        fwval_lib.run_command("quartus_pgm -c %d -m JTAG --status --status_type=\"CONFIG\"" %(test.dut.dut_cable))
        fwval_lib.print_err("\nREPORT :: FAILED due to Exception")

        #log the traceback into stderr
        logging.exception('')
        
        # main error handler
        test.main_error_handler(dut_closed)
        
        exit(-1)
        
main()
```

Please note that this is a Python script for testing a device with RSU (Remote System Update). The script uses command line arguments to set the testing parameters, loads the required bitstream files, sets up the test environment, performs JIC programming using Quartus PGM command, configures QSPI prefetcher for BFM, attempts RSU switch image to a non-existent image, and verifies the results. If any error occurs, the script will log the error and exit with a non-zero status.