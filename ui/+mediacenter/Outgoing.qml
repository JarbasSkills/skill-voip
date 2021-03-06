/*
 * Copyright 2020 by Aditya Mehra <aix.m@outlook.com>
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *    http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 *
 */

import QtQuick.Layouts 1.4
import QtQuick 2.9
import QtQuick.Controls 2.2
import org.kde.kirigami 2.8 as Kirigami
import org.kde.lottie 1.0
import Mycroft 1.0 as Mycroft

Item {
    id: incomingView
    
    ColumnLayout {
        anchors.fill: parent
        
        Component.onCompleted: {
            rejectButton.forceActiveFocus()
        }
            
        LottieAnimation {
            id: l1
            Layout.fillWidth: true
            Layout.fillHeight: true
            source: Qt.resolvedUrl("../animations/outgoing.json")
            loops: Animation.Infinite
            fillMode: Image.PreserveAspectFit
            running: true
            
            onSourceChanged: {
                console.log(l1.status)
            }
        }
        
        Item {
            id: bottomAreaA
            Layout.fillWidth: true
            Layout.preferredHeight: Kirigami.Units.gridUnit * 2
            
            Kirigami.Heading {
                id: connectionTextHeading
                level: 1
                wrapMode: Text.WordWrap
                anchors.centerIn: parent
                font.bold: true
                text: voipLoaderView.contactName != "Unknown" ? "Calling " + voipLoaderView.contactName : "Calling Unknown"
                color: Kirigami.Theme.linkColor
            }
        }
        
        ColumnLayout {
            id: bottomAreaB
            Layout.fillWidth: true
            Layout.preferredHeight: Kirigami.Units.gridUnit * 10
            Layout.leftMargin: Kirigami.Units.gridUnit * 2
            Layout.rightMargin: Kirigami.Units.gridUnit * 2
            spacing: Kirigami.Units.largeSpacing
                        
            Button {
                id: rejectButton
                Layout.fillWidth: true
                Layout.preferredHeight: Kirigami.Units.gridUnit * 4
                
                background: Rectangle {
                    color: "red"
                    radius: Kirigami.Units.gridUnit
                    border.width: rejectButton.activeFocus ? 1 : 0
                    border.color: rejectButton.activeFocus ? Kirigami.Theme.linkColor : "transparent"
                }
                
                contentItem: Item {
                    Image {
                        anchors.centerIn: parent
                        width: Kirigami.Units.iconSizes.medium
                        height: width
                        source: "../images/phone-reject.png"
                    }
                }
                
                onClicked: {
                    triggerGuiEvent("voip.jarbas.hangCall", {})
                }
                
                Keys.onReturnPressed: {
                    clicked()
                }
            }
        }
    }
}
 
 
