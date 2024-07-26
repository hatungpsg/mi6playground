# -*- coding: utf-8 -*-

import sys
import os
import re
import zipfile
import shutil
import argparse
import logging
import random

# Importing the public API Module
import fwval

#yi zhi's library
import fwval_lib

# Parse argument from parent test
parser = argparse.ArgumentParser()
parser.add_argument('--conf', default="avstx16", help='config mode for DUT')
parser.add_argument('--msel', default="13", help='msel for DUT')
parser.add_argument('--debug_cmf', default="0", help='debug_cmf')
parser.add_argument('--debug_cmf_zip', default="empty", help='debug_cmf firmware path')
parser.add_argument('--curve', default="384", help='debug_cmf')
parser.add_argument('--signed_encrypted_sof', default="outputfiles/qky1_encrypted_or_gate_design.sof", help='signed_encrypted_sof file')
parser.add_argument('--signed_unencrypted_sof', default="outputfiles/qky1_unencrypted_or_gate_design.sof", help='signed_unencrypted_sof')
parser.add_argument('--unsigned_unencrypted_sof')
parser.add_argument('--gen_tool', default="pfg", help='Tools to generate signed encrypted bitstream: pfg or advance ')
parser.add_argument('--init_unencrypted', default="0", help='Initialize with unencrypted bitstream if set to 1')
parser.add_argument('--init_unsigned_unencrypted', default="0", help='Initialize with unsigned unencrypted bitstream if set to 1')
parser.add_argument('--unencrypt_test', default="0", help='Run configuration using unencrypted bitstream after program AES key if set to 1')
parser.add_argument('--recovery', default="0", help='Run recovery test if set to 1')
parser.add_argument('--reprogram_same_aeskey', default="0", help='Run test that reprogram same user aes key if set to 1')
parser.add_argument('--reprogram_aeskey', default="0", help='Run test that reprogram a different user aes key if set to 1')
parser.add_argument('--debug_programmerhelper', default="0", help='Program user key and aes key using Programmer with helper if set to 1')
parser.add_argument('--qek_program', help='Program user aes key: sdm or programmer')
parser.add_argument('--count', default="2", help='Reconfigure count')
parser.add_argument('--board_rev', default="RevC", help='board revision')
parser.add_argument('--key_storage', help='Encryption key storage select')
parser.add_argument('--family', help='dut family')
parser.add_argument('--test_flow', default="main", help='Whether to use the production or provision flow')
parser.add_argument('--test_mode', default="0", help='Whether to use UDS test mode or not, with selection of 0-3')
parser.add_argument('--aes_test_mode', default="None", help='Whether to use AES test mode')
parser.add_argument('--non_volatile', default="off", help='Whether to use physical flow to program AES key')
parser.add_argument('--dump_trace', default="off", help='Whether to dump emulator trace or not')

args = parser.parse_args()

msel_set = eval(args.msel)
debug_cmf = eval(args.debug_cmf)
curve = eval(args.curve)
gen_tool = args.gen_tool
config_mode = (args.conf).upper()
debug_cmf_zip = args.debug_cmf_zip
signed_encrypted_sof = args.signed_encrypted_sof
signed_unencrypted_sof = args.signed_unencrypted_sof
unsigned_unencrypted_sof = args.unsigned_unencrypted_sof
init_unencrypted = eval(args.init_unencrypted)
init_unsigned_unencrypted = eval(args.init_unsigned_unencrypted)
unencrypt_test = eval(args.unencrypt_test)
recovery = eval(args.recovery)
reprogram_same_aeskey = eval(args.reprogram_same_aeskey)
reprogram_aeskey = eval(args.reprogram_aeskey)
qek_program = args.qek_program
debug_programmerhelper = eval(args.debug_programmerhelper)
reconfig_count = eval(args.count)
assert reconfig_count > 0, "Count must not less than 1: %d" % reconfig_count
board_rev = args.board_rev
family = args.family
key_storage = args.key_storage
test_flow = args.test_flow
test_mode = eval(args.test_mode)
aes_test_mode = args.aes_test_mode
dump_trace = args.dump_trace
if aes_test_mode != "None":
    aes_test_mode = eval(aes_test_mode)
else:
    aes_test_mode = None
non_volatile_flag = args.non_volatile

signed_encrypted_sof = fwval_lib.execution_lib.getsof(input_file=signed_encrypted_sof)
print("Set key_storage to: %s" % key_storage)
print("Set MSEL to: %d" % msel_set)
# print("Set encrypted_sof to: %s" % encrypted_sof)
print("Set signed_encrypted_sof to: %s" % signed_encrypted_sof)



'''
Method :: This is the main section of test execution
'''
def main():
    #initilize test environment
    dut_closed = False

    # Files for authentication
    fuse_info_txt="fuse.txt"

    # to be remove after sm7 emu support
    if "Emu" in family:
        family_input = "agilex"
    else:
        family_input = family

    # Checks the current quartus version
    current_acds_version = os.environ['QUARTUS_VERSION']
    current_acds_build   = int(os.environ['ACDS_BUILD_NUMBER'])   #get acds build number
    compare_quartus = fwval_lib.compare_quartus_version(current_acds_version,'21.1')
    sdm_version = os.getenv('DUT_SDM_VERSION')
    dut_sfe = os.getenv('DUT_SFE')

    # Starting from 21.1 B122, we are using sof signed with new qky files signed
    # using the rootkeys stored in qky folder due to new AES CCERT method
    # For 21.1 B122 and below, we are using old qky files
    if (compare_quartus == 1) or (compare_quartus == 0 and current_acds_build>=122) : #current acds version is newer than 21.1
        pem_file = "qky/" + family_input + "/" + family_input + "_priv3_qky1.pem"
        qky_file = "qky/" + family_input + "/" + family_input + "_keychain_qky1.qky"
    else:
        pem_file = "qky/" + family_input + "/priv3_qky1.pem"
        qky_file = "qky/" + family_input + "/keychain_qky1.qky"

    pem_file_aes = "qky/" + family_input + "/" + family_input + "_priv3_qky1_aes_ccert.pem"
    qky_file_aes = "qky/" + family_input + "/" + family_input + "_keychain_qky1_aes_ccert.qky"

    # Files for encryption
    passphrase_file = "qek_pass.txt"
    qek_file = "aeskey1.qek"
    qek_file2 = "aeskey2.qek"

    global aes_test_mode, test_mode

    if ((sdm_version == "1.5" and dut_sfe == "0") and (test_mode == 0 or test_mode == None)):
        test_mode = random.randint(1, 3)
        print("WARNING ::  Real UDS EFUSE value is use in non-sfe and this is expected to fail, turning on test mode %d"%(test_mode))

    if (aes_test_mode == None and test_mode != 0 and test_mode != None):
        aes_test_mode = random.randint(0, 5)
        print("WARNING :: non aes test mode bitstream is use in UDS test mode env and this is expected to fail, turning on aes test mode %d"%(aes_test_mode))


    if (os.environ.get("FWVAL_PLATFORM") == 'emulator'):
        emulator = 1
    else:
        emulator = 0

    try:
        #setup test environment
        test = fwval_lib.JtagTest(configuration="jtag", msel=msel_set, rev=board_rev)

        # Initialize Security Data-type & mode as JTAG
        testOBJ = fwval_lib.SecurityDataTypes('Encryption TEST')
        testOBJ.HANDLES['DUT']=test.dut
        testOBJ.configuration_source = "jtag"

        # Find nadder.zip path
        nadder_zip = fwval_lib.find_nadder_zip(debug_cmf, debug_cmf_zip)
        
        if init_unsigned_unencrypted == 1:
            # unsigned_unencrypted_sof
            global unsigned_unencrypted_sof
            unsigned_unencrypted_sof = fwval_lib.execution_lib.getsof(input_file=unsigned_unencrypted_sof)
            sofname3 = os.path.basename(unsigned_unencrypted_sof)
            sofname3 = os.path.splitext(sofname3)[0]
            rbf_unsigned_unencrypted = sofname3 + ".rbf"
            fwval_lib.pfg_generate_rbf(input_sof=unsigned_unencrypted_sof, output_rbf=rbf_unsigned_unencrypted, config_mode=config_mode, fw_source=nadder_zip)

        # signed_unencrypted_sof
        global signed_unencrypted_sof
        signed_unencrypted_sof = fwval_lib.execution_lib.getsof(input_file=signed_unencrypted_sof)
        sofname2 = os.path.basename(signed_unencrypted_sof)
        sofname2 = os.path.splitext(sofname2)[0]
        rbf_signed_unencrypted = sofname2 + ".rbf"
        fwval_lib.pfg_generate_rbf(input_sof=signed_unencrypted_sof, output_rbf=rbf_signed_unencrypted, config_mode=config_mode, fw_source=nadder_zip, pem_file=pem_file, qky_file=qky_file, family=family_input)

        # Generate a passphrase file
        fwval_lib.run_command("echo iloveencryption > " + passphrase_file)

        # Generate an AES key
        testOBJ.generate_base_aes_key(aes_base_key='aes_key.txt',aes_test_mode=aes_test_mode, separator='random')
        testOBJ.generate_aes_key(aes_base_key='aes_key.txt', aes_password=passphrase_file, aes_key_qek=qek_file, family=family_input)
        if ((recovery == 1) or (reprogram_aeskey==1)) :
            aes_test_mode_2 = aes_test_mode
            if aes_test_mode != None:
                while aes_test_mode_2 == aes_test_mode:
                    aes_test_mode_2 = random.randint(0, 5)
            testOBJ.generate_base_aes_key(aes_base_key='aes_key2.txt',aes_test_mode=aes_test_mode_2, separator='random')
            testOBJ.generate_aes_key(aes_base_key='aes_key2.txt', aes_password=passphrase_file, aes_key_qek=qek_file2, family=family_input)

        ## Generate the signed encrypted bitstream 1,2 with AES key 1,2 respectively
        #/ Pass
        sofname = os.path.basename(signed_encrypted_sof)
        sofname = os.path.splitext(sofname)[0]
        rbf_signed = "signed_encrypted_" + sofname + ".rbf"
        rbf_signed2 = "signed_encrypted2_" + sofname + ".rbf"

        fwval_lib.pfg_generate_rbf(input_sof=signed_encrypted_sof, output_rbf=rbf_signed, config_mode=config_mode, pem_file=pem_file, qky_file=qky_file, qek_file=qek_file, password=passphrase_file, fw_source=nadder_zip, family=family_input)
        if ((recovery == 1) or (reprogram_aeskey==1)) :
            fwval_lib.pfg_generate_rbf(input_sof=signed_encrypted_sof, output_rbf=rbf_signed2, config_mode=config_mode, pem_file=pem_file, qky_file=qky_file, qek_file=qek_file2, password=passphrase_file, fw_source=nadder_zip, family=family_input)
    except:
        #log the traceback into stderr
        logging.exception('')

        fwval_lib.assert_err(0, "ERROR :: Failed to prepare the signed encrypted bitstream")

    try:

        fwval_lib.print_stdout()

        ## Power cycle with nconfig=1
        #/ Pass
        test.power_cycle(nconfig=1)
        #update expectation for pins and config_status
        test.update_exp(nconfig=1, nstatus=1)

        if (not emulator):
            try:
                ## Initial configuration with good bitstream
                #/ Bitstream fail as expected but firmware loaded successfully
                print("TEST :: To bring up initial firmware")
                local_checks = []

                if init_unencrypted == 1:
                    print("Initial configuration with signed unencrypted bitstream")
                    # Initial configuration with signed unencrypted bitstream
                    local_checks.extend(test.complete_jtag_config(file_path=rbf_signed_unencrypted, success=1, before_cmf_state=0, skip=1, skip_ver=1,
                        exp_err="JTAG programming time exceeds the maximum", failed_cmf_state=1))
                elif init_unsigned_unencrypted == 1:
                    print("Initial configuration with unsigned unencrypted bitstream")
                    # Initial configuration with unsigned unencrypted bitstream
                    local_checks.extend(test.complete_jtag_config(file_path=rbf_unsigned_unencrypted, success=1, before_cmf_state=0, skip=1, skip_ver=1))
                else:
                    print("Initial configuration with signed encrypted bitstream")
                    # Initial configuration with signed encrypted bitstream
                    local_checks.extend(test.complete_jtag_config(file_path=rbf_signed, success=0, before_cmf_state=0, skip=1,skip_ver=1,
                        exp_err="JTAG programming time exceeds the maximum", failed_cmf_state=1))


                #check pin and status verification (if didn't assert them)
                for check in local_checks:
                    assert check, "ERROR :: One or more of the pin/status verifications failed during initial configuration"

            except:
                #log the traceback into stderr
                logging.exception('')

                fwval_lib.assert_err(0, "ERROR :: Unexpected result in initial configuration")

        ## Load provision firmware
        #/ Pass
        ## Send efuse write disable
        #/ Pass
        ## Program keychain into EFUSE
        #/ Pass
        testOBJ.handle_engineering_flow(dutHANDLE=test,qky_file=qky_file,test_mode=test_mode)

        try:
            fwval_lib.print_stdout()

            local_checks = []

            if key_storage == "BBRAM":
                ## Clear AES key if BBRAM flow
                #/ Pass
                test.jtag_volatile_aes_erase()
            # program aes key in main flow
            if test_flow == "main":
                local_checks.append(test.complete_jtag_config(file_path=rbf_signed_unencrypted, success=1, before_cmf_state=1, skip=1, skip_ver=1, test_mode=test_mode))

            ## Program AES Key 1
            #* BBRAM
            #* EFUSE
            #/ AES key program successfully
            local_checks.append(test.program_aeskey(qek=qek_file, pem_file=pem_file_aes, qky_file=qky_file_aes,
                passphrase_file=passphrase_file, option=qek_program, key_storage=key_storage, non_volatile=non_volatile_flag, debug_programmerhelper=debug_programmerhelper, success=True))


            if (test_flow == "prov" and key_storage == "BBRAM" and not emulator):
                print("TEST :: For BBRAM direct transition to main CMF is disabled hence perform POR and program qky virtually")
                
                ## Power cycle with nconfig=1 if BBRAM
                #/ Pass
                test.power_cycle(nconfig=1)

                ## Load provision firmware
                #/ Pass
                ## Send efuse write disable
                #/ Pass
                ## Program keychain into EFUSE
                #/ Pass
                testOBJ.handle_engineering_flow(dutHANDLE=test,qky_file=qky_file,test_mode=test_mode)

            #check pin and status verification (if didn't, assert them)
            for check in local_checks:
                assert check, "ERROR :: program_aeskey response is not [0]!"
                print("INFO :: Successfully program AES key with key_storage: %s, qek: %s" %(key_storage,qek_file))

        except:
            #log the traceback into stderr
            logging.exception('')

            fwval_lib.print_err("ERROR :: Failed to program_aeskey via SDM command using %s" % qek_file)

            # Collect trace
            test.collect_pgm_trace()

        ## Load signed encrypted bitstream 1 via JTAG
        #/ Bitstream loaded successfully
        loop_pass = 0
        for count in range(reconfig_count):
            local_pass = 1
            if reprogram_same_aeskey == 1:
                print("TEST :: Loop %d for reprogram the same AES key and reconfiguration"%count)

                try:
                    fwval_lib.print_stdout()

                    local_checks = []

                    # Program AES Key
                    local_checks.append(test.program_aeskey(qek=qek_file, pem_file=pem_file_aes, qky_file=qky_file_aes,
                        passphrase_file=passphrase_file, option=qek_program, key_storage=key_storage, non_volatile=non_volatile_flag, debug_programmerhelper=debug_programmerhelper, success=True))

                    #check pin and status verification (if didn't, assert them)
                    for check in local_checks:
                        assert check, "ERROR :: program_aeskey response is not [0]!"
                        print("INFO :: Successfully program AES key with key_storage: %s, qek: %s" %(key_storage,qek_file))

                except:
                    #log the traceback into stderr
                    logging.exception('')

                    fwval_lib.print_err("ERROR :: Failed to program_aeskey via SDM command using %s" % qek_file)

                    # Collect trace
                    test.collect_pgm_trace()

            else:
                print("TEST :: Loop %d for reconfiguration"%count)

            try:
                print("TEST :: Expected passed in configuration using AES key matched bitstream")
                local_checks = []

                local_checks.extend(test.complete_jtag_config(file_path=rbf_signed, before_cmf_state=1, skip=1, success=1, skip_ver=1, test_mode=test_mode))
                local_checks.append(test.verify_design_andor(rbf_signed))

                #check pin and status verification (if didn't assert them)
                for check in local_checks:
                    assert check, "ERROR :: One or more of the pin/status verifications failed"

            except:
                local_pass = 0
                #log the traceback into stderr
                logging.exception('')

                fwval_lib.print_err("ERROR :: Unexpected result for configuration using signed encrypted bitstream - count %d"%count)

                # Collect trace
                test.collect_pgm_trace()

            if local_pass == 0 :
                print("ERROR :: Test failed for loop %d"% count)
            else:
                loop_pass+=1
            print("TEST :: Test passed for loop %d"% count)

        print("TEST :: %d/%d loop is passing for AES key matched bitstream" %(loop_pass, reconfig_count))

        ## Load signed unencrypted bitstream via JTAG
        #/ Bitstream loaded successfully        
        if not emulator:
            if unencrypt_test == 1:
                loop_pass = 0
                for count in range(reconfig_count):
                    print("TEST :: Loop %d for reconfiguration using signed unencrypted bitstream"%count)
                    local_pass = 1
                    try:
                        print("TEST :: Expected passed in configuration using signed unencrypted bitstream")
                        local_checks=[]

                        local_checks.extend(test.complete_jtag_config(file_path=rbf_signed_unencrypted, before_cmf_state=1, skip=1, success=1, skip_ver=1,test_mode=test_mode))
                        local_checks.append(test.verify_design_andor(rbf_signed_unencrypted))

                        #check pin and status verification (if didn't assert them)
                        for check in local_checks:
                            assert check, "ERROR :: One or more of the pin/status verifications failed"

                    except:
                        local_pass = 0
                        #log the traceback into stderr
                        logging.exception('')

                        fwval_lib.print_err("ERROR :: Unexpected result for configuration using signed unencrypted bitstream - count %d"%count)

                        # Collect trace
                        test.collect_pgm_trace()

                    if local_pass == 0 :
                        print("ERROR :: Test failed for loop %d"% count)
                    else:
                        loop_pass+=1

                    print("TEST :: Test passed for loop %d"% count)

                print("TEST :: %d/%d loop is passing for signed unencrypted bitstream" %(loop_pass, reconfig_count))

            

        # dump emulator trace
        if(dump_trace == "on"):
            print("\nDumping emulator trace...")
            test.dump_trace()
        #close dut, set it as empty test
        print("\nClose DUT")
        test.dut.close()
        dut_closed = True

        #check if any sys-console left and kill them
        fwval_lib.delay(1000)
        fwval_lib.kill_all_syscon()
        exit(0)

    except Exception as e:
        fwval_lib.print_err("\nREPORT :: FAILED due to Exception")

        #log the traceback into stderr
        logging.exception('')

        # main error handler
        test.main_error_handler(dut_closed)

        exit(-1)

main()
