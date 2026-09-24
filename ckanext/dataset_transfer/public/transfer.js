$(document).ready(function(){
    
    check_user_has_api_token_and_show_message();

    /**
     * Click on the next button
     */
    $('#dataset_transfer_next_btn').click(function(){
        let step = $(this).attr("step");
        if( step === "2"){
            // console.info($('#token_exist_box').is(':checked'))
            if($('#token_exist_box').prop('checked') === false && $('#transfer_api_token_input').val() === ""){                
                $('#api_token_input_empty_alert_box').show();
            }
            else if ($('#token_exist_box').prop('checked') === true){
                check_user_has_api_token();
            }
            else{
                // GoToStep2();
                $('#publish_step1').hide();
                $('#publish_step2').show();
                $(this).attr("step", "3");
            }
        }
        else if (step === "3"){          
            if($('#terms_of_usage').prop('checked') !== true || $('#rights_of_use').prop('checked') !== true){
                $("#no_consent_alert_message").show();
            }
            else{
                $('#publish_step1').hide();
                $('#publish_step2').hide();
                $('#publish_step3').show();
                $(this).attr("step", "4");
                $(this).hide();
                $('#dataset_transfer_submit').show();
            }
        }
    });

    
    /**
     * Click on the publish button
     */
     $('#dataset_transfer_submit').click(function(event){
        event.preventDefault();
        if ($(this).data('publishing') === true) {
            return;
        }
        $(this).data('publishing', true);
        $(this).prop('disabled', true);
        $('#publish_step3').hide();
        $('#action_btn_part').hide();
        $('#publish_failed_section').hide();
        $('#publish_result_section').hide();
        $('#publish_step_final').show();
        let dest_url = $('#publish_url').val();        
        let formdata = new FormData();
        formdata.set('package_id', $('#package_id').val());        
        formdata.set('api_token', $("#transfer_api_token_input").val());
        formdata.set('save_api_token_box', $("#save_api_token_box").prop('checked'));
        formdata.set('token_exist_box', $("#token_exist_box").prop('checked'));
        formdata.set('terms_of_usage', $("#terms_of_usage").prop('checked'));
        formdata.set('rights_of_use', $("#rights_of_use").prop('checked'));
        let req = new XMLHttpRequest();
        req.timeout = 30 * 60 * 1000;
        console.info("Dataset transfer publish request started", dest_url);
        req.onload = function() {
            console.info("Dataset transfer publish response received", req.status, req.responseText);
            let data = parse_publish_response(req.responseText);
            if (req.status >= 200 && req.status < 300 && data && data.success !== false && !data.error) {
                show_publish_success(data);
            }
            else {
                show_publish_failure(
                    data && data.error ? data.error : "HTTP " + req.status,
                    data && data.message ? data.message : get_publish_error_message(req)
                );
            }
        };
        req.onerror = function() {
            console.error("Dataset transfer publish request failed");
            show_publish_failure("Network error", "The publish request could not reach the server.");
        };
        req.ontimeout = function() {
            console.error("Dataset transfer publish request timed out");
            show_publish_failure("Timeout", "Publishing took too long and the browser stopped waiting. Please check the dataset page before trying again.");
        };
        req.onabort = function() {
            console.error("Dataset transfer publish request aborted");
            show_publish_failure("Aborted", "The publish request was aborted.");
        };
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


     $('#dataset_transfer_org_list').click(function(){
        $('#organization_empty_box_alert').hide();
     });

     $('.consent-box').click(function(){
        $('#no_consent_alert_message').hide();
     });

});

function parse_publish_response(responseText){
    if (responseText === "500") {
        return {"success": false, "error": "Unknown", "message": "None"};
    }
    try {
        return JSON.parse(responseText);
    }
    catch(error) {
        console.error("Dataset transfer publish response was not valid JSON", error, responseText);
        return null;
    }
}

function get_publish_error_message(req){
    if (req.responseText) {
        return req.responseText.substring(0, 1000);
    }
    return "The server did not return a usable response.";
}

function show_publish_success(data){
    console.info("Dataset transfer publish succeeded", data);
    $('#publish_step_final').hide();
    $('#publish_failed_section').hide();
    $('#publish_result_section').show();
    $('#published_doi').text(data['doi'] || '');
    $('#published_url').find('a').attr("href", data['published_url']);
    $('#published_url').find('a').text(data['published_url']);
}

function show_publish_failure(error, message){
    console.error("Dataset transfer publish failed", error, message);
    $('#publish_step_final').hide();
    $('#publish_result_section').hide();
    $('#publish_failed_section').show();
    $('#published_fail_type').text(error || "Unknown");
    $('#published_fail_message').text(message || "None");
    $('#dataset_transfer_submit').data('publishing', false);
    $('#dataset_transfer_submit').prop('disabled', false);
}


function check_user_has_api_token(){
    let dest_url = $('#check_api_token').val();
    let req = new XMLHttpRequest();
    req.onreadystatechange = function() {
        if (req.readyState == XMLHttpRequest.DONE && req.status === 200){            
            if(req.responseText === "True"){                
                // GoToStep2();
                $('#publish_step1').hide();
                $('#publish_step2').show();
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


function check_user_has_api_token_and_show_message(){
    let dest_url = $('#check_api_token').val();
    let req = new XMLHttpRequest();
    req.onreadystatechange = function() {
        if (req.readyState == XMLHttpRequest.DONE && req.status === 200) {       
            if(req.responseText === "True"){                
                $('#api_token_exist_info_box').show();
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
    formdata.set('token_exist_box', $("#token_exist_box").prop('checked'));
    let req = new XMLHttpRequest();
    req.onreadystatechange = function() {
        if (req.readyState == XMLHttpRequest.DONE && req.status === 200) {
            let orgList = JSON.parse(this.responseText);            
            if(orgList.length === 0){
                $('.org_should_exist').hide();
                $('#no_org_message').show();
            }
            else{
                $('#no_org_message').hide();                
                $('#dataset_transfer_org_list').select2({
                    data:orgList,
                    width:'50%'
                });                
            }
            $('#publish_step1').hide();
            $('#publish_step2').show();
        }
    }
    req.open("POST", dest_url);
    req.send(formdata);
}
