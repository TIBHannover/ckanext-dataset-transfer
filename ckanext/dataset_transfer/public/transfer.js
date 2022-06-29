$(document).ready(function(){ 

    /**
     * Click on the next button
     */
    $('#dataset_transfer_next_btn').click(function(){
        let step = $(this).attr("step");
        if( step === "2"){
            if($('#token_exist_box').prop('checked') === false && $('#transfer_api_token_input').val() === ""){
                $('#api_token_input_empty_alert_box').show();
            }
            else if ($('#token_exist_box').prop('checked') === true){
                check_user_has_api_token();
            }
            else{
                GoToStep2();
                $(this).attr("step", "3");
            }
        }
        else if (step === "3"){
            $('#publish_step1').hide();
            $('#publish_step2').hide();
            $('#publish_step3').show();
            $(this).attr("step", "4");
            $(this).hide();
            $('#dataset_transfer_submit').show();
        }
    });

    
    /**
     * Click on the publish button
     */
     $('#dataset_transfer_submit').click(function(){
        $('#publish_step3').hide();
        $('#action_btn_part').hide();
        $('#publish_step_final').show();
        let dest_url = $('#publish_url').val();
        let org_name = $('#dataset_transfer_org_list').select2('data').text;
        let formdata = new FormData();
        formdata.set('package_id', $('#package_id').val());
        formdata.set('org', org_name);
        formdata.set('api_token', $("#transfer_api_token_input").val());
        formdata.set('save_api_token_box', $("#save_api_token_box").prop('checked'));
        formdata.set('token_exist_box', $("#token_exist_box").prop('checked'));
        let req = new XMLHttpRequest();
        req.onreadystatechange = function() {
        if (req.readyState == XMLHttpRequest.DONE && req.status === 200) {       
                if(this.responseText !== "500"){
                    $('#publish_step_final').hide(); 
                    $('#publish_result_section').show();
                    let data = JSON.parse(this.responseText);
                    $('#published_doi').text(data['doi']);
                    $('#published_url').find('a').attr("href", data['published_url']);
                    $('#published_url').find('a').text(data['published_url']);
                }
            
            }
        }
        req.open("POST", dest_url);
        req.send(formdata);
    });


    /**
     * Check the "use existing token checkbox"
     */
    $('#token_exist_box').click(function(){
        $('#api_token_input_empty_alert_box').hide();
        $('#api_token_not_exist_alert_box').hide();
        if($(this).prop('checked') === true){
            $("#transfer_api_token_input").prop('disabled', true);
            $("#save_api_token_box").prop('disabled', true);
            $("#save_api_token_box").closest('label').css('color', "gray");
            $("#save_api_token_box").prop('checked', false);
        }
        else{
            $("#transfer_api_token_input").prop('disabled', false);
            $("#save_api_token_box").prop('disabled', false);
            $("#save_api_token_box").closest('label').css('color', "#333333");
        }
    });


    /**
     * Hide the alert when api token input changes
     */
     $('#transfer_api_token_input').keydown(function(){
        $('#api_token_input_empty_alert_box').hide();
        $('#api_token_not_exist_alert_box').hide();
     });

});


function check_user_has_api_token(){
    let dest_url = $('#check_api_token').val();
    let req = new XMLHttpRequest();
    req.onreadystatechange = function() {
        if (req.readyState == XMLHttpRequest.DONE && req.status === 200) {       
            if(req.responseText === "True"){                
                GoToStep2();
                $('#dataset_transfer_next_btn').attr("step", "3");
            }
            else{
                $('#api_token_not_exist_alert_box').show();
            }            
        }
    }
    req.open("GET", dest_url);
    req.send();
}




function GoToStep2(){
    let dest_url = $('#org_list_call').val();
    let formdata = new FormData();
    formdata.set('package_id', $('#package_id').val());
    formdata.set('api_token', $("#transfer_api_token_input").val());
    let req = new XMLHttpRequest();
    req.onreadystatechange = function() {
        if (req.readyState == XMLHttpRequest.DONE && req.status === 200) {       
            $('#dataset_transfer_org_list').select2({
                data:JSON.parse(this.responseText),
                width:'50%'
            });
            $('#publish_step1').hide();
            $('#publish_step2').show();
        }
    }
    req.open("POST", dest_url);
    req.send(formdata);
}
