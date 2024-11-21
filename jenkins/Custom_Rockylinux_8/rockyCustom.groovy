pipeline {
    agent any
    environment {
        ROCKY_ISO_URL = "https://download.rockylinux.org/pub/rocky/8/isos/x86_64/Rocky-8-latest-x86_64-minimal.iso"
        CUSTOM_ISO_NAME = "Custom-RockyLinux-8.iso"
        WORKSPACE_DIR = "${env.WORKSPACE}/custom_iso"
        EXISTING_ISO_PATH = "/var/lib/jenkins/workspace/Rocky-8.10-x86_64-minimal.iso"
    }
    stages {
        stage('Setup Build Environment') {
            steps {
                script {
                    // Clean workspace before running
                    sh 'rm -rf ${WORKSPACE_DIR}'
                    sh 'mkdir -p ${WORKSPACE_DIR}'
                }
            }
        }
        stage('Check and Download Rocky Linux ISO') {
            steps {
                script {
                    if (fileExists(EXISTING_ISO_PATH)) {
                        echo "Using existing ISO from ${EXISTING_ISO_PATH}"
                        sh "cp ${EXISTING_ISO_PATH} ${WORKSPACE_DIR}/Rocky-8.iso"
                    } else {
                        echo "ISO not found at ${EXISTING_ISO_PATH}, downloading..."
                        sh "curl -L -o ${WORKSPACE_DIR}/Rocky-8.iso ${ROCKY_ISO_URL}"
                    }
                }
            }
        }
        stage('Extract ISO') {
            steps {
                sh '''
                mkdir -p ${WORKSPACE_DIR}/custom_iso_contents
                7z x ${WORKSPACE_DIR}/Rocky-8.iso -o${WORKSPACE_DIR}/custom_iso_contents
                '''
            }
        }
        stage('Modify Kickstart File for Automated Installation') {
            steps {
                script {
                    def kickstartContent = '''
                        install
                        lang en_US.UTF-8
                        keyboard de
                        timezone Germany/Berlin
                        rootpw --plaintext f4x4d8p6
                        bootloader --location=mbr
                        clearpart --all --initlabel
                        autopart
                        reboot

                        %packages
                        @core
                        docker
                        %end

                        %post
                        systemctl enable docker
                        %end
                    '''
                    writeFile file: "${WORKSPACE_DIR}/custom_iso_contents/ks.cfg", text: kickstartContent
                }
            }
        }
        stage('Update Boot Configurations') {
            steps {
                sh '''
                # Update boot options to use the custom kickstart file
                sed -i 's|append|append inst.ks=cdrom:/ks.cfg|' ${WORKSPACE_DIR}/custom_iso_contents/isolinux/isolinux.cfg
                '''
            }
        }
        stage('Create Custom ISO') {
            steps {
                sh '''
                mkisofs -o ${WORKSPACE_DIR}/${CUSTOM_ISO_NAME} \
                -b isolinux/isolinux.bin \
                -c isolinux/boot.cat \
                -no-emul-boot -boot-load-size 4 -boot-info-table \
                -V "CUSTOM_ROCKY_LINUX" \
                -J -R -v \
                ${WORKSPACE_DIR}/custom_iso_contents
                '''
            }
        }
    }
    post {
        always {
            archiveArtifacts artifacts: 'custom_iso/*.iso', allowEmptyArchive: true
            sh 'rm -rf ${WORKSPACE_DIR}'
        }
    }
}
